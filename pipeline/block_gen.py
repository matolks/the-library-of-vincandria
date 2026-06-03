"""
pipeline/block_gen.py

Agent 3 — Teaching block generation.

Turns a topic plus its retrieved chunks into an ordered sequence of typed
BlockNote-compatible blocks. See pipeline/AGENT3_DESIGN.md for the locked
contracts.

This file currently contains `get_topic_context`, the pure-read
context-gathering step. Subsequent additions will build the prompt, validate
output, and reconcile against pinned cohorts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Optional

from pipeline import db
from pipeline.fingerprints import fingerprint_payload
from pipeline import llm
from pipeline.prompt import OUTPUT_FORMAT_VERSION, PROMPT_VERSION


logger = logging.getLogger(__name__)


# ---- dataclasses ----------------------------------------------------------

@dataclass(frozen=True)
class TopicRow:
    id: str
    slug: str
    title: str
    summary: Optional[str]
    course_slug: str


@dataclass(frozen=True)
class PrereqTopic:
    slug: str
    title: str
    summary: Optional[str]


@dataclass(frozen=True)
class ChunkContext:
    id: str
    content: str
    content_hash: str
    source_path: str
    page_number: Optional[int]
    similarity: float  # cosine similarity in approx. [0, 1]; higher = closer


@dataclass(frozen=True)
class ExistingBlock:
    id: str
    order: int
    type: str
    content: dict
    group_id: Optional[str]
    manually_edited: bool
    generation_metadata: Optional[dict]


@dataclass(frozen=True)
class BlockCohort:
    """A pinned-set candidate: either a singleton ungrouped block or a full group.

    Per §4 of AGENT3_DESIGN.md, a cohort is pinned (preserved across regeneration)
    if any of its members has manually_edited=True. The flag is not propagated
    to siblings on save; the expansion is computed here at read time.
    """
    group_id: Optional[str]  # None for singletons
    blocks: tuple[ExistingBlock, ...]  # ordered by `order`
    pinned: bool


@dataclass(frozen=True)
class TopicContext:
    topic: TopicRow
    prereqs: tuple[PrereqTopic, ...]
    chunks: tuple[ChunkContext, ...]  # similarity-floor filtered, ordered desc
    cohorts: tuple[BlockCohort, ...]  # in topic order; filter .pinned for anchors
    coverage: str  # 'dense' if any chunk in top-K cleared the floor, else 'sparse'
    top_similarity: float  # max similarity over the unfiltered top-K (0.0 if none)


@dataclass(frozen=True)
class StaleDecision:
    stale: bool
    reason: str
    expected_fingerprint: str
    stored_fingerprints: tuple[str, ...]


# ---- main entrypoint ------------------------------------------------------

def get_topic_context(
    topic_id: str,
    *,
    chunk_k: int = 8,
    chunk_similarity_floor: float = 0.70,
) -> TopicContext:
    """Gather every read this topic's prompt + reconciler will need.

    Pure read. No LLM, no writes. Uses the shared psycopg2 connection from
    db.get_conn().

    The coverage flag is set to 'sparse' when no chunk in the unfiltered top-K
    clears `chunk_similarity_floor`. block_gen should refuse to generate on
    sparse topics; they are the queue for Agent 4 web enrichment.

    Raises ValueError if the topic does not exist or has no embedding.
    """
    topic = _fetch_topic(topic_id)
    prereqs = _fetch_prereqs(topic_id)
    blocks = _fetch_blocks(topic_id)
    chunks_unfiltered = _fetch_chunks(topic_id, chunk_k)
    top_similarity = max(
        (c.similarity for c in chunks_unfiltered), default=0.0
    )
    coverage = "dense" if top_similarity >= chunk_similarity_floor else "sparse"
    chunks = tuple(
        c for c in chunks_unfiltered if c.similarity >= chunk_similarity_floor
    )
    cohorts = _build_cohorts(blocks)
    return TopicContext(
        topic=topic,
        prereqs=prereqs,
        chunks=chunks,
        cohorts=cohorts,
        coverage=coverage,
        top_similarity=top_similarity,
    )


# ---- private fetchers -----------------------------------------------------

def _fetch_topic(topic_id: str) -> TopicRow:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.slug, t.title, t.summary, c.slug
            FROM "Topic" t
            JOIN "Course" c ON c.id = t."courseId"
            WHERE t.id = %s
            """,
            (topic_id,),
        )
        row = cur.fetchone()
    if row is None:
        raise ValueError(f"Topic not found: {topic_id}")
    return TopicRow(
        id=row[0], slug=row[1], title=row[2], summary=row[3], course_slug=row[4]
    )


def _fetch_prereqs(topic_id: str) -> tuple[PrereqTopic, ...]:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.slug, t.title, t.summary
            FROM "TopicEdge" e
            JOIN "Topic" t ON t.id = e."fromId"
            WHERE e."toId" = %s AND e.kind = 'PREREQUISITE_OF'
            ORDER BY t.slug
            """,
            (topic_id,),
        )
        rows = cur.fetchall()
    return tuple(PrereqTopic(slug=r[0], title=r[1], summary=r[2]) for r in rows)


def _fetch_blocks(topic_id: str) -> tuple[ExistingBlock, ...]:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, "order", type, content, group_id,
                   manually_edited, generation_metadata
            FROM "Block"
            WHERE "topicId" = %s
            ORDER BY "order"
            """,
            (topic_id,),
        )
        rows = cur.fetchall()
    return tuple(
        ExistingBlock(
            id=r[0],
            order=r[1],
            type=r[2],
            content=_as_dict(r[3]) or {},
            group_id=r[4],
            manually_edited=r[5],
            generation_metadata=_as_dict(r[6]),
        )
        for r in rows
    )


def _fetch_chunks(topic_id: str, k: int) -> tuple[ChunkContext, ...]:
    """Wrap db.top_chunks_for_topic and convert distance to similarity.

    Returns the full unfiltered top-K. The similarity floor is applied by
    get_topic_context so the unfiltered top similarity remains available for
    the coverage flag.
    """
    rows = db.top_chunks_for_topic(topic_id, k=k)
    return tuple(
        ChunkContext(
            id=r["id"],
            content=r["content"],
            content_hash=r.get("contentHash") or _sha256_text(r["content"]),
            source_path=r["sourcePath"],
            page_number=r["pageNumber"],
            similarity=1.0 - float(r["distance"]),
        )
        for r in rows
    )


# ---- cohort expansion -----------------------------------------------------

def _build_cohorts(blocks: tuple[ExistingBlock, ...]) -> tuple[BlockCohort, ...]:
    """Partition blocks into cohorts and apply §4 atomic pinning.

    Ungrouped blocks become singleton cohorts. Blocks sharing a group_id form
    one cohort each. A cohort is pinned iff any member has manually_edited=True.
    Cohorts are returned ordered by the `order` of their first member.
    """
    groups: dict[str, list[ExistingBlock]] = {}
    singletons: list[ExistingBlock] = []
    for b in blocks:
        if b.group_id is None:
            singletons.append(b)
        else:
            groups.setdefault(b.group_id, []).append(b)

    cohorts: list[BlockCohort] = []
    for b in singletons:
        cohorts.append(
            BlockCohort(group_id=None, blocks=(b,), pinned=b.manually_edited)
        )
    for gid, members in groups.items():
        members.sort(key=lambda m: m.order)
        cohorts.append(
            BlockCohort(
                group_id=gid,
                blocks=tuple(members),
                pinned=any(m.manually_edited for m in members),
            )
        )
    cohorts.sort(key=lambda c: c.blocks[0].order)
    return tuple(cohorts)


# ---- helpers --------------------------------------------------------------

def _as_dict(value) -> Optional[dict]:
    """psycopg2 returns jsonb as dict by default; tolerate str just in case."""
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    return json.loads(value)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _resolve_topic_id(slug: str) -> str:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute('SELECT id FROM "Topic" WHERE slug = %s', (slug,))
        row = cur.fetchone()
    if row is None:
        raise SystemExit(f"No topic with slug={slug!r}")
    return row[0]


def _resolve_generation_targets(
    course_slug: str, topic_slug: str | None, topic_slugs: tuple[str, ...] = ()
) -> list[tuple[str, str]]:
    selected_slugs = _normalize_topic_filters(topic_slug, topic_slugs)
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.slug
            FROM "Topic" t
            JOIN "Course" c ON c.id = t."courseId"
            WHERE c.slug = %s
              AND (%s::text[] IS NULL OR t.slug = ANY(%s::text[]))
            ORDER BY t."order"
            """,
            (course_slug, selected_slugs or None, selected_slugs or None),
        )
        rows = cur.fetchall()
    if not rows:
        if selected_slugs:
            raise SystemExit(
                f"No matching topic slugs in course={course_slug!r}: "
                f"{', '.join(selected_slugs)}"
            )
        raise SystemExit(f"No topics in course={course_slug!r}")
    found = {r[1] for r in rows}
    missing = [slug for slug in selected_slugs if slug not in found]
    if missing:
        raise SystemExit(
            f"Topic slug(s) not found in course={course_slug!r}: "
            f"{', '.join(missing)}"
        )
    return [(r[0], r[1]) for r in rows]


def _normalize_topic_filters(
    topic_slug: str | None, topic_slugs: tuple[str, ...] = ()
) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw in ((topic_slug,) if topic_slug else ()) + topic_slugs:
        for part in str(raw).split(","):
            slug = part.strip()
            if not slug or slug in seen:
                continue
            seen.add(slug)
            normalized.append(slug)
    return normalized


def _load_topic_slugs_file(path: str | None) -> tuple[str, ...]:
    if not path:
        return ()
    slugs: list[str] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            stripped = line.split("#", 1)[0].strip()
            if not stripped:
                continue
            slugs.extend(part.strip() for part in stripped.split(",") if part.strip())
    return tuple(slugs)


def agent3_generation_config(
    *,
    model: str | None = None,
    max_tokens: int = llm.DEFAULT_MAX_TOKENS,
    temperature: float = llm.DEFAULT_TEMPERATURE,
    structured_json: bool = llm.DEFAULT_STRUCTURED_JSON,
) -> dict:
    """Return the behavior-affecting Agent 3 config included in fingerprints."""
    return {
        "model": model or llm.DEFAULT_MODEL,
        "decoding": {
            "max_tokens": max_tokens,
            "temperature": temperature,
        },
        "structured_json": structured_json,
        "output_format_version": OUTPUT_FORMAT_VERSION,
    }


def should_use_structured_json(context: TopicContext) -> bool:
    """Route code/pseudocode-heavy topics through Anthropic JSON-schema mode."""
    if any(cohort.pinned for cohort in context.cohorts):
        return False

    haystack = " ".join(
        [
            context.topic.course_slug,
            context.topic.slug,
            context.topic.title,
            context.topic.summary or "",
            *(chunk.content[:1000] for chunk in context.chunks),
        ]
    ).lower()
    markers = (
        "algorithm",
        "pseudocode",
        "code",
        "programming",
        "matlab",
        "python",
        "runtime",
        "complexity",
    )
    return any(marker in haystack for marker in markers)


def compute_context_fingerprint(
    context: TopicContext,
    *,
    generation_config: dict | None = None,
) -> str:
    """Fingerprint the inputs Agent 3 actually depends on."""
    generation_config = generation_config or agent3_generation_config()
    pinned_anchors = []
    for cohort in context.cohorts:
        if not cohort.pinned:
            continue
        pinned_anchors.append(
            {
                "group_id": cohort.group_id,
                "blocks": [
                    {
                        "id": block.id,
                        "type": block.type,
                        "content": block.content,
                        "group_id": block.group_id,
                    }
                    for block in cohort.blocks
                ],
            }
        )

    return fingerprint_payload(
        {
            "topic": {
                "slug": context.topic.slug,
                "title": context.topic.title,
                "summary": context.topic.summary,
            },
            "prompt_version": PROMPT_VERSION,
            "generation_config": generation_config,
            "source_chunks": [
                {"id": chunk.id, "content_hash": chunk.content_hash}
                for chunk in context.chunks
            ],
            "prerequisite_topic_slugs": [p.slug for p in context.prereqs],
            "pinned_anchors": pinned_anchors,
        }
    )


def topic_has_persisted_blocks(topic_id: str) -> bool:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            'SELECT 1 FROM "Block" WHERE "topicId" = %s LIMIT 1',
            (topic_id,),
        )
        return cur.fetchone() is not None


def strip_invalid_source_ids(
    blocks: list[dict],
    allowed_chunk_ids: set[str],
    *,
    topic_slug: str | None = None,
) -> None:
    """Drop hallucinated provenance IDs while preserving valid model citations."""
    for index, block in enumerate(blocks):
        meta = block.get("generation_metadata")
        if not isinstance(meta, dict):
            continue
        ids = meta.get("source_chunk_ids")
        if not isinstance(ids, list):
            continue

        valid_ids = [chunk_id for chunk_id in ids if chunk_id in allowed_chunk_ids]
        dropped_ids = [chunk_id for chunk_id in ids if chunk_id not in allowed_chunk_ids]
        if not dropped_ids:
            continue

        for chunk_id in dropped_ids:
            logger.warning(
                "Dropping invalid source_chunk_id=%r topic=%s block_index=%s block_id=%s",
                chunk_id,
                topic_slug or "(unknown)",
                index,
                block.get("id") or "(new)",
            )
        meta["source_chunk_ids"] = valid_ids


def topic_is_stale(topic_id: str) -> bool:
    return explain_topic_staleness(topic_id).stale


def explain_topic_staleness(
    topic_id: str,
    *,
    generation_config: dict | None = None,
) -> StaleDecision:
    context = get_topic_context(topic_id)
    if not context.cohorts:
        fresh = compute_context_fingerprint(
            context, generation_config=generation_config
        )
        return StaleDecision(True, "missing_blocks", fresh, ())
    fresh = compute_context_fingerprint(
        context, generation_config=generation_config
    )
    stored = tuple(sorted({
        block.generation_metadata.get("context_fingerprint")
        for cohort in context.cohorts
        for block in cohort.blocks
        if isinstance(block.generation_metadata, dict)
        and block.generation_metadata.get("context_fingerprint")
    }))
    if fresh in stored:
        return StaleDecision(False, "fingerprint_match", fresh, stored)
    if not stored:
        return StaleDecision(True, "missing_context_fingerprint", fresh, stored)
    return StaleDecision(True, "fingerprint_mismatch", fresh, stored)


# ---- CLI ------------------------------------------------------------------

def _print_context(ctx: TopicContext) -> None:
    print("=== TOPIC ===")
    print(f"  {ctx.topic.slug} — {ctx.topic.title}")
    print(f"  course:   {ctx.topic.course_slug}")
    print(f"  summary:  {ctx.topic.summary or '(none)'}")
    print(f"  coverage: {ctx.coverage.upper()}  (top_similarity={ctx.top_similarity:.3f})")

    print(f"\n=== PREREQS ({len(ctx.prereqs)}) ===")
    for p in ctx.prereqs:
        print(f"  {p.slug} — {p.title}")

    print(f"\n=== CHUNKS ({len(ctx.chunks)} above floor, by similarity desc) ===")
    if ctx.coverage == "sparse":
        print("  (none — topic is SPARSE; block_gen should refuse until Agent 4 enrichment)")
    for c in ctx.chunks:
        page = f" p.{c.page_number}" if c.page_number is not None else ""
        preview = c.content[:140].replace("\n", " ")
        ellipsis = "..." if len(c.content) > 140 else ""
        print(f"  [{c.similarity:.3f}] {c.source_path}{page}  id={c.id}")
        print(f"          {preview}{ellipsis}")

    total_blocks = sum(len(c.blocks) for c in ctx.cohorts)
    pinned_cohorts = sum(1 for c in ctx.cohorts if c.pinned)
    pinned_blocks = sum(len(c.blocks) for c in ctx.cohorts if c.pinned)
    print(
        f"\n=== COHORTS ({len(ctx.cohorts)} total, {total_blocks} blocks; "
        f"{pinned_cohorts} pinned cohort(s), {pinned_blocks} pinned block(s)) ==="
    )
    for c in ctx.cohorts:
        tag = "PINNED" if c.pinned else "      "
        gid = f"group={c.group_id}" if c.group_id else "singleton"
        if len(c.blocks) == 1:
            order_range = f"#{c.blocks[0].order}"
        else:
            order_range = f"#{c.blocks[0].order}-{c.blocks[-1].order}"
        print(f"  {tag} {order_range} {gid} ({len(c.blocks)} block(s))")
        for b in c.blocks:
            edited = "[edited]" if b.manually_edited else "        "
            print(f"      {edited} #{b.order} {b.type} id={b.id}")


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate teaching blocks for a course or inspect one topic context.",
    )
    parser.add_argument("--course", help="course slug for generation")
    parser.add_argument("--topic", help="optional topic slug for generation")
    parser.add_argument("--topics",
                        help="comma-separated topic slugs for selective generation")
    parser.add_argument("--topics-file",
                        help="file of topic slugs, one per line or comma-separated; # comments allowed")
    parser.add_argument("--dry-run", action="store_true",
                        help="validate model output without writing blocks")
    parser.add_argument("--missing-only", action="store_true",
                        help="generate only topics with no persisted blocks")
    parser.add_argument("--stale-only", action="store_true",
                        help="generate only topics with no blocks or changed context")
    parser.add_argument("--force-all", action="store_true",
                        help="generate all targets even when --missing-only/--stale-only would skip")
    parser.add_argument("--model",
                        help="Agent 3 model override; included in context fingerprints")
    parser.add_argument("--max-tokens", type=int, default=llm.DEFAULT_MAX_TOKENS,
                        help=f"Agent 3 max_tokens (default: {llm.DEFAULT_MAX_TOKENS})")
    parser.add_argument("--temperature", type=float, default=llm.DEFAULT_TEMPERATURE,
                        help=f"Agent 3 temperature (default: {llm.DEFAULT_TEMPERATURE})")
    parser.set_defaults(structured_json=None)
    parser.add_argument("--structured-json", dest="structured_json",
                        action="store_true",
                        help="force Anthropic JSON-schema output_config")
    parser.add_argument("--no-structured-json", dest="structured_json",
                        action="store_false",
                        help="disable Anthropic JSON-schema output_config")
    parser.add_argument("--json", action="store_true",
                        help="emit full GenerationResult objects as JSON")
    parser.add_argument("--include-preview", action="store_true",
                        help="with --dry-run --json, include the validated reconciler sequence")
    parser.add_argument("--pause-seconds", type=float, default=0.0,
                        help="sleep between topic generations to respect API rate limits")
    parser.add_argument("--topic-slug",
                        help="legacy context-inspection mode for one topic")
    parser.add_argument("--k", type=int, default=8, help="top-K chunks (default: 8)")
    parser.add_argument(
        "--floor",
        type=float,
        default=0.70,
        help="coverage floor in [0, 1]; topic is SPARSE if top similarity below this (default: 0.70)",
    )
    args = parser.parse_args()

    try:
        if args.topic_slug:
            topic_id = _resolve_topic_id(args.topic_slug)
            ctx = get_topic_context(
                topic_id,
                chunk_k=args.k,
                chunk_similarity_floor=args.floor,
            )
            _print_context(ctx)
            return

        if not args.course:
            raise SystemExit("--course is required unless --topic-slug is used")

        from dataclasses import asdict

        from pipeline.orchestrator import generate_blocks_for_topic

        topic_slugs = tuple(_normalize_topic_filters(
            args.topics, _load_topic_slugs_file(args.topics_file)
        ))
        targets = _resolve_generation_targets(args.course, args.topic, topic_slugs)
        totals = {
            "topics": len(targets),
            "skipped": 0,
            "ok": 0,
            "refused_sparse": 0,
            "failed_validation": 0,
            "failed_parse": 0,
            "blocks_written": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_tokens": 0,
            "cache_read_tokens": 0,
            "usd_cost": 0.0,
        }

        for i, (topic_id, slug) in enumerate(targets):
            if i and args.pause_seconds > 0:
                time.sleep(args.pause_seconds)
            if args.missing_only and not args.force_all and topic_has_persisted_blocks(topic_id):
                totals["skipped"] += 1
                if not args.json:
                    print(f"{slug}: skipped reason=existing_blocks")
                else:
                    print(json.dumps({
                        "topic_id": topic_id,
                        "slug": slug,
                        "status": "skipped",
                        "reason": "existing_blocks",
                    }, sort_keys=True))
                continue
            if args.stale_only and not args.force_all:
                topic_context = get_topic_context(topic_id)
                use_structured_json = (
                    args.structured_json
                    if args.structured_json is not None
                    else should_use_structured_json(topic_context)
                )
                generation_config = agent3_generation_config(
                    model=args.model,
                    max_tokens=args.max_tokens,
                    temperature=args.temperature,
                    structured_json=use_structured_json,
                )
                stale = explain_topic_staleness(
                    topic_id,
                    generation_config=generation_config,
                )
                if stale.stale:
                    if not args.json:
                        print(
                            f"{slug}: regenerating reason={stale.reason} "
                            f"fingerprint={stale.expected_fingerprint}"
                        )
                else:
                    totals["skipped"] += 1
                    if not args.json:
                        print(
                            f"{slug}: skipped reason={stale.reason} "
                            f"fingerprint={stale.expected_fingerprint}"
                        )
                    else:
                        print(json.dumps({
                            "topic_id": topic_id,
                            "slug": slug,
                            "status": "skipped",
                            "reason": stale.reason,
                            "context_fingerprint": stale.expected_fingerprint,
                            "stored_fingerprints": stale.stored_fingerprints,
                        }, sort_keys=True))
                    continue
            elif args.force_all and (args.missing_only or args.stale_only):
                if not args.json:
                    print(f"{slug}: regenerating reason=force_all")
            result = generate_blocks_for_topic(
                topic_id,
                dry_run=args.dry_run,
                model=args.model,
                max_tokens=args.max_tokens,
                temperature=args.temperature,
                structured_json=args.structured_json,
                include_preview=args.include_preview,
            )
            if args.json:
                print(json.dumps(asdict(result), sort_keys=True))
            else:
                print(
                    f"{slug}: status={result.status} attempts={result.attempts} "
                    f"blocks={result.blocks_written} "
                    f"cost=${result.usd_cost:.4f} "
                    f"top_similarity={result.top_similarity:.3f}"
                )

            if result.status in totals:
                totals[result.status] += 1
            totals["blocks_written"] += result.blocks_written
            totals["input_tokens"] += result.input_tokens
            totals["output_tokens"] += result.output_tokens
            totals["cache_creation_tokens"] += result.cache_creation_tokens
            totals["cache_read_tokens"] += result.cache_read_tokens
            totals["usd_cost"] += result.usd_cost

        print(
            "TOTAL: "
            f"topics={totals['topics']} ok={totals['ok']} "
            f"skipped={totals['skipped']} "
            f"refused_sparse={totals['refused_sparse']} "
            f"failed_validation={totals['failed_validation']} "
            f"failed_parse={totals['failed_parse']} "
            f"blocks={totals['blocks_written']} "
            f"input_tokens={totals['input_tokens']} "
            f"output_tokens={totals['output_tokens']} "
            f"cache_create={totals['cache_creation_tokens']} "
            f"cache_read={totals['cache_read_tokens']} "
            f"cost=${totals['usd_cost']:.4f} "
            f"dry_run={args.dry_run}"
        )
    finally:
        db.close()


if __name__ == "__main__":
    _main()
