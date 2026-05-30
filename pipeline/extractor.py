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

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    raise EnvironmentError("ANTHROPIC_API_KEY is not set in .env")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

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


def _build_user_prompt(course: str, chunks: list[dict]) -> str:
    group_list = json.dumps(TOPIC_GROUPS, indent=2)

    # Concatenate chunk texts, labelled by file and page for context
    passages = []
    for c in chunks:
        label = f"[{c['file']} p.{c['page']} chunk {c['chunk_index']}]"
        passages.append(f"{label}\n{c['text']}")

    combined = "\n\n---\n\n".join(passages)

    # Truncate if absurdly long -- Claude's context is large but be defensive
    max_chars = 180_000
    if len(combined) > max_chars:
        combined = combined[:max_chars] + "\n\n[truncated]"

    return f"""Course: {course}

Suggested topic groups:
{group_list}

Course text (chunked):
{combined}

Extract all topics from this course and assign them to groups."""


def extract_topics(course_slug: str, chunks: list[dict]) -> dict:
    """
    Call Claude to extract topics from chunks.
    Returns the parsed JSON response dict.
    """
    course_name = course_slug.replace("-", " ").title()
    prompt = _build_user_prompt(course_name, chunks)

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()

    try:
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Agent 1 returned invalid JSON: {e}\n\nRaw output:\n{raw}")


def write_topics(course_slug: str, extraction: dict) -> dict[str, str]:
    """
    Write extracted topics and groups to Supabase.
    Returns a mapping of topic slug -> topic_id for downstream agents.
    """
    # Upsert course
    course_name = extraction.get(
        "course", course_slug.replace("-", " ").title())
    course_id = db.upsert_course(slug=course_slug, name=course_name)

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

    return topic_id_map


def run(course_slug: str, chunks: list[dict]) -> dict[str, str]:
    """
    Full Agent 1 run: extract then write.
    Returns topic slug -> topic_id map for use by mapper and block_gen.
    """
    print(f"\n[Agent 1] Extracting topics for: {course_slug}")
    extraction = extract_topics(course_slug, chunks)
    print(f"  Found {len(extraction.get('topics', []))} topics")
    topic_id_map = write_topics(course_slug, extraction)
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
        course_name = args.course.replace("-", " ").title()
        result = extract_topics(args.course, chunks)
        print(json.dumps(result, indent=2))
    else:
        topic_id_map = run(args.course, chunks)
        print(f"\nTopic ID map:\n{json.dumps(topic_id_map, indent=2)}")
