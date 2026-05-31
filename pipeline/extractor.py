"""
pipeline/extractor.py

Agent 1: Topic extraction and group assignment.
Takes chunked text for a course, returns structured topics with group assignments.

Each call processes one course worth of chunks.
Output is written to Supabase via db.py.

Topic groups are suggested to the model -- it assigns based on content and can
create new groups if nothing fits. Existing groups are passed as context.
"""

import os
import json
import anthropic
from dotenv import load_dotenv
from pipeline import db
from pipeline.embeddings import embed_documents
from pipeline.db import set_topic_embeddings

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise EnvironmentError("ANTHROPIC_API_KEY is not set in .env")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# Pricing per million tokens (USD). Update if Anthropic changes pricing.
# Sonnet 4.x: $3 input / $15 output (verify at anthropic.com/pricing).
PRICE_INPUT_PER_MTOK = float(os.getenv("CLAUDE_PRICE_INPUT", "3.00"))
PRICE_OUTPUT_PER_MTOK = float(os.getenv("CLAUDE_PRICE_OUTPUT", "15.00"))

def _extract_json(text: str) -> str:
    """Extract JSON object/array from model output, tolerating fences and prose."""
    candidates = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not candidates:
        raise ValueError(f"No JSON found in response: {text[:300]}")
    start = min(candidates)
    end = max(text.rfind("}"), text.rfind("]"))
    if end < start:
        raise ValueError(f"Malformed JSON boundaries: {text[:300]}")
    return text[start:end + 1]

TOPIC_GROUPS = [
    {"slug": "math-foundations",        "name": "Math Foundations",
        "description": "Calculus, Linear Algebra, Fourier Analysis"},
    {"slug": "engineering-foundations", "name": "Engineering Foundations",
        "description": "VLSI, FPGA Design"},
    {"slug": "programming-software",    "name": "Programming & Software",
        "description": "Data Structures, Algorithms, OS internals"},
    {"slug": "computer-systems",        "name": "Computer Systems",
        "description": "Operating Systems, Computer Architecture"},
    {"slug": "hardware-circuits",       "name": "Hardware & Circuits",
        "description": "Digital Logic, Electronics"},
    {"slug": "signals-networks",        "name": "Signals & Networks",
        "description": "DSP, Networking, Communications"},
    {"slug": "engineering-communication", "name": "Engineering Communication",
        "description": "Technical Writing, Documentation"},
]

SYSTEM_PROMPT = """You are an expert curriculum analyst. Given chunked text from a university course, 
you extract the distinct topics covered and assign each to one or more broad subject groups.

Rules:
- A topic is a coherent concept or technique that could stand as its own page (e.g. "Fourier Transform", "malloc internals", "Bode plots").
- Do not create topics for administrative content (syllabi, grading policies, course logistics).
- A topic can belong to multiple groups if it genuinely spans them.
- You are given a suggested list of groups. Use them when they fit. If a topic belongs to a group not on the list, create a new group with a sensible slug and name.
- Return only valid JSON. No preamble, no explanation, no markdown fences.
- Course slugs are NOT group slugs. Groups are broad subjects spanning many courses (e.g. math-foundations, computer-systems). Never create a group named after the course itself or use the course slug as a group.
- Every slug in any topic's "groups" array must either be a suggested group or appear in "new_groups". No exceptions.

Output schema:
{
  "course": "<course name>",
  "new_groups": [
    {"slug": "...", "name": "...", "description": "..."}
  ],
  "topics": [
    {
      "title": "...",
      "slug": "...",
      "summary": "One or two sentence description of what this topic covers.",
      "key_concepts": ["...", "..."],
      "groups": ["slug-one", "slug-two"],
      "order_in_course": 1
    }
  ]
}

new_groups is empty if all topics fit existing groups.
slug must be lowercase, hyphenated, globally unique (prefix with course slug if needed).
order_in_course is the integer position this topic appears in the course, starting at 1.
"""


def _build_user_prompt(course: str, chunks: list[dict], existing: list[dict]) -> str:
    group_list = json.dumps(TOPIC_GROUPS, indent=2)

    passages = []
    for c in chunks:
        label = f"[{c['file']} p.{c['page']} chunk {c['chunk_index']}]"
        passages.append(f"{label}\n{c['text']}")
    combined = "\n\n---\n\n".join(passages)

    max_chars = 180_000
    if len(combined) > max_chars:
        combined = combined[:max_chars] + "\n\n[truncated]"

    existing_block = ""
    if existing:
        existing_json = json.dumps(existing, indent=2)
        existing_block = f"""
Existing topics for this course (from previous runs):
{existing_json}

IMPORTANT: If a topic you are extracting matches one of the existing topics above (same concept, even if the title is slightly reworded), reuse the existing slug exactly. Only generate a new slug for genuinely new topics. This keeps URLs stable across re-runs.
"""

    return f"""Course: {course}

Suggested topic groups:
{group_list}
{existing_block}
Course text (chunked):
{combined}

Extract all topics from this course and assign them to groups."""


def extract_topics(course_slug: str, chunks: list[dict], existing: list[dict] | None = None) -> dict:
    """
    Call Claude to extract topics from chunks.
    Returns the parsed JSON response dict.
    """
    course_name = course_slug.replace("-", " ").title()
    prompt = _build_user_prompt(course_name, chunks, existing or [])

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        temperature=0,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    usage = response.usage
    cost = (
        usage.input_tokens / 1_000_000 * PRICE_INPUT_PER_MTOK
        + usage.output_tokens / 1_000_000 * PRICE_OUTPUT_PER_MTOK
    )
    print(
        f"  [usage] in={usage.input_tokens:,} tok  "
        f"out={usage.output_tokens:,} tok  "
        f"cost=${cost:.4f}  "
        f"model={MODEL}"
    )
    raw = response.content[0].text
    try:
        return json.loads(_extract_json(raw))
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError(f"Agent 1 returned invalid JSON: {e}\n\nRaw output:\n{raw}")


def write_topics(course_slug: str, extraction: dict, chunks: list[dict]) -> dict[str, str]:
    """
    Write extracted topics and groups to Supabase.
    Returns a mapping of topic slug -> topic_id for downstream agents.
    """
    # Upsert course
    course_name = extraction.get(
        "course", course_slug.replace("-", " ").title())
    course_id = db.upsert_course(slug=course_slug, name=course_name)
    # Embed and persist chunks
    if chunks:
        from pipeline.embeddings import embed_documents
        import hashlib
        # Strip null bytes (PDF extraction artifacts); Postgres TEXT rejects them
        chunk_texts = [c["text"] for c in chunks]
        chunk_vectors = embed_documents(chunk_texts)

        records = [
            db.ChunkRecord(
                content=text,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                source_path=c["file"],
                source_type=c["source_type"],
                chunk_index=c["chunk_index"],
                page_number=c.get("page"),
                section_path=None,
                token_count=None,
            )
            for c, text in zip(chunks, chunk_texts)
        ]
        for r, vec in zip(records, chunk_vectors):
            r.embedding = vec
        db.upsert_chunks(course_id, records)
        touched = {(r.source_path, r.chunk_index) for r in records}
        orphans = db.delete_orphan_chunks(course_id, touched)
        print(f"  Chunks: {len(records)} written, {orphans} orphan(s) removed")
    # Upsert all known groups
    group_id_map: dict[str, str] = {}
    for g in TOPIC_GROUPS:
        gid = db.upsert_topic_group(
            slug=g["slug"], name=g["name"], description=g["description"])
        group_id_map[g["slug"]] = gid

    # Upsert any new groups the model created
    for g in extraction.get("new_groups", []):
        gid = db.upsert_topic_group(
            slug=g["slug"], name=g["name"], description=g.get("description"))
        group_id_map[g["slug"]] = gid

    # Upsert topics
    topic_id_map: dict[str, str] = {}
    for t in extraction.get("topics", []):
        group_ids = [group_id_map[s]
                     for s in t.get("groups", []) if s in group_id_map]
        topic_id = db.upsert_topic(
            slug=t["slug"],
            title=t["title"],
            summary=t.get("summary"),
            order=t["order_in_course"],
            course_id=course_id,
            group_ids=group_ids,
        )
        topic_id_map[t["slug"]] = topic_id
        print(f"  Topic: {t['title']} -> groups: {t.get('groups', [])}")
    # Delete orphans from previous runs
    keep = list(topic_id_map.keys())
    orphans = db.delete_orphan_topics(course_id, keep)
    if orphans:
        print(f"  Removed {orphans} orphan topic(s) from previous runs")
    # Embed topics and write vectors
    topics = extraction.get("topics", [])
    if topics:
        texts = [
            f"{t['title']}\n{t.get('summary', '')}\n"
            f"Key concepts: {', '.join(t.get('key_concepts', []))}"
            for t in topics
        ]
        vectors = embed_documents(texts)
        pairs = [(topic_id_map[t["slug"]], vec) for t, vec in zip(topics, vectors)]
        set_topic_embeddings(pairs)
        print(f"  Embedded {len(vectors)} topics")

    return topic_id_map


def run(course_slug: str, chunks: list[dict]) -> dict[str, str]:
    """
    Full Agent 1 run: extract then write.
    Returns topic slug -> topic_id map for use by mapper and block_gen.
    """
    print(f"\n[Agent 1] Extracting topics for: {course_slug}")
    existing = db.get_existing_topics_for_course(course_slug)
    if existing:
        print(f"  Found {len(existing)} existing topics; passing as slug anchors")

    extraction = extract_topics(course_slug, chunks, existing=existing)
    print(f"  Found {len(extraction.get('topics', []))} topics")

    topic_id_map = write_topics(course_slug, extraction, chunks)
    print(f"  Written to database")
    return topic_id_map


# ---------------------------------------------------------------------------
# CLI (run Agent 1 in isolation against a saved chunk JSON)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run Agent 1 (topic extraction) on a chunk file.")
    parser.add_argument("--course", required=True, help="Course slug")
    parser.add_argument("--chunks", required=True,
                        help="Path to chunk JSON from chunker.py")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print extraction result, do not write to DB")
    args = parser.parse_args()

    with open(args.chunks) as f:
        chunks = json.load(f)

    if args.dry_run:
        existing = db.get_existing_topics_for_course(args.course)
        result = extract_topics(args.course, chunks, existing=existing)
        print(json.dumps(result, indent=2))
    else:
        topic_id_map = run(args.course, chunks)
        print(f"\nTopic ID map:\n{json.dumps(topic_id_map, indent=2)}")
