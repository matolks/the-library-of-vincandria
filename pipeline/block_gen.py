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
import json
from dataclasses import dataclass
from typing import Optional

from pipeline import db


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


def _resolve_topic_id(slug: str) -> str:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute('SELECT id FROM "Topic" WHERE slug = %s', (slug,))
        row = cur.fetchone()
    if row is None:
        raise SystemExit(f"No topic with slug={slug!r}")
    return row[0]


# ---- CLI for eyeballing ---------------------------------------------------

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
        description="Inspect the context block_gen will see for one topic.",
    )
    parser.add_argument("--topic-slug", required=True)
    parser.add_argument("--k", type=int, default=8, help="top-K chunks (default: 8)")
    parser.add_argument(
        "--floor",
        type=float,
        default=0.70,
        help="coverage floor in [0, 1]; topic is SPARSE if top similarity below this (default: 0.70)",
    )
    args = parser.parse_args()

    try:
        topic_id = _resolve_topic_id(args.topic_slug)
        ctx = get_topic_context(
            topic_id,
            chunk_k=args.k,
            chunk_similarity_floor=args.floor,
        )
        _print_context(ctx)
    finally:
        db.close()


if __name__ == "__main__":
    _main()