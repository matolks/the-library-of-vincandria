"""
Minimal live-course regression harness for Agent 3 content generation.

Checks the database state that block generation depends on and writes:
- no sparse topics remain before generation;
- persisted block schemas are valid;
- generated source_chunk_ids resolve to same-course Chunk rows;
- pinned group anchors are internally contiguous;
- prerequisite cycles are absent;
- manually excluded mapper edges are not present.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field

from pipeline import db
from pipeline.block_schema import validate_block_schema
from pipeline.mapper import Edge, detect_cycle
from scripts.drop_bad_edges import BAD_EDGES


@dataclass
class EvalCheck:
    name: str
    ok: bool
    failures: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


@dataclass
class EvalReport:
    course_slug: str
    ok: bool
    checks: list[EvalCheck]


def run_content_generation_evals(
    course_slug: str,
    *,
    weak_floor: float = 0.70,
    strong_floor: float = 0.75,
    strong_min: int = 3,
    k: int = 8,
) -> EvalReport:
    checks = [
        _check_no_sparse_topics(course_slug, weak_floor, strong_floor, strong_min, k),
        _check_all_topics_have_blocks(course_slug),
        _check_block_schemas(course_slug),
        _check_source_chunk_ids_resolve(course_slug),
        _check_pinned_anchor_integrity(course_slug),
        _check_prereq_cycles_absent(course_slug),
        _check_known_bad_edges_excluded(),
    ]
    return EvalReport(
        course_slug=course_slug,
        ok=all(c.ok for c in checks),
        checks=checks,
    )


def _course_topic_rows(course_slug: str) -> list[dict]:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.slug, t.title
            FROM "Topic" t
            JOIN "Course" c ON c.id = t."courseId"
            WHERE c.slug = %s
            ORDER BY t."order"
            """,
            (course_slug,),
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    if not rows:
        raise ValueError(f"No topics found for course {course_slug!r}")
    return rows


def _check_no_sparse_topics(
    course_slug: str,
    weak_floor: float,
    strong_floor: float,
    strong_min: int,
    k: int,
) -> EvalCheck:
    failures: list[str] = []
    topic_details: list[dict] = []
    for topic in _course_topic_rows(course_slug):
        chunks = db.top_chunks_for_topic(topic["id"], k=k)
        sims = [1.0 - float(c["distance"]) for c in chunks]
        top = max(sims, default=0.0)
        strong = sum(1 for s in sims if s >= strong_floor)
        if top < weak_floor:
            failures.append(
                f"{topic['slug']}: top similarity {top:.3f} below weak floor {weak_floor:.2f}"
            )
        topic_details.append(
            {
                "slug": topic["slug"],
                "top_similarity": round(top, 3),
                "strong_chunks": strong,
                "thin": top >= weak_floor and strong < strong_min,
            }
        )
    thin = [t["slug"] for t in topic_details if t["thin"]]
    return EvalCheck(
        "no_sparse_topics_before_generation",
        not failures,
        failures,
        {
            "topics": len(topic_details),
            "weak_floor": weak_floor,
            "strong_floor": strong_floor,
            "strong_min": strong_min,
            "thin_topics": thin,
        },
    )


def _check_all_topics_have_blocks(course_slug: str) -> EvalCheck:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.slug, count(b.id) AS block_count
            FROM "Topic" t
            JOIN "Course" c ON c.id = t."courseId"
            LEFT JOIN "Block" b ON b."topicId" = t.id
            WHERE c.slug = %s
            GROUP BY t.id
            ORDER BY t."order"
            """,
            (course_slug,),
        )
        rows = cur.fetchall()
    failures = [slug for slug, block_count in rows if block_count == 0]
    return EvalCheck(
        "all_topics_have_blocks",
        not failures,
        failures,
        {"topics": len(rows), "missing_blocks": len(failures)},
    )


def _check_block_schemas(course_slug: str) -> EvalCheck:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.slug, b.id, b.type, b.content, b.generation_metadata
            FROM "Block" b
            JOIN "Topic" t ON t.id = b."topicId"
            JOIN "Course" c ON c.id = t."courseId"
            WHERE c.slug = %s
            ORDER BY t."order", b."order"
            """,
            (course_slug,),
        )
        rows = cur.fetchall()

    failures: list[str] = []
    for topic_slug, block_id, block_type, content, meta in rows:
        block = _stored_content_to_generated_shape(block_type, content, meta)
        errors = validate_block_schema(block)
        if errors:
            failures.append(f"{topic_slug}/{block_id}: {'; '.join(errors)}")
    return EvalCheck(
        "block_schemas_valid",
        not failures,
        failures,
        {"blocks_checked": len(rows)},
    )


def _stored_content_to_generated_shape(block_type: str, content, meta) -> dict:
    if isinstance(content, dict):
        block = dict(content)
    else:
        block = {"type": block_type, "content": content}
    block.setdefault("type", block_type)
    if meta is not None:
        block["generation_metadata"] = meta
    return block


def _check_source_chunk_ids_resolve(course_slug: str) -> EvalCheck:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.slug, b.id, b.generation_metadata
            FROM "Block" b
            JOIN "Topic" t ON t.id = b."topicId"
            JOIN "Course" c ON c.id = t."courseId"
            WHERE c.slug = %s AND b.generation_metadata IS NOT NULL
            ORDER BY t."order", b."order"
            """,
            (course_slug,),
        )
        rows = cur.fetchall()

    referenced: set[str] = set()
    failures: list[str] = []
    for topic_slug, block_id, meta in rows:
        ids = meta.get("source_chunk_ids") if isinstance(meta, dict) else None
        if ids is None:
            continue
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            failures.append(f"{topic_slug}/{block_id}: source_chunk_ids is not string[]")
            continue
        referenced.update(ids)

    if referenced:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ch.id
                FROM "Chunk" ch
                JOIN "Course" c ON c.id = ch."courseId"
                WHERE c.slug = %s AND ch.id = ANY(%s)
                """,
                (course_slug, list(referenced)),
            )
            resolved = {r[0] for r in cur.fetchall()}
        missing = sorted(referenced - resolved)
        if missing:
            failures.append(f"missing or cross-course chunk ids: {missing}")

    return EvalCheck(
        "source_chunk_ids_resolve",
        not failures,
        failures,
        {"blocks_with_metadata": len(rows), "unique_chunk_ids": len(referenced)},
    )


def _check_pinned_anchor_integrity(course_slug: str) -> EvalCheck:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.slug, b.id, b."order", b.group_id, b.manually_edited
            FROM "Block" b
            JOIN "Topic" t ON t.id = b."topicId"
            JOIN "Course" c ON c.id = t."courseId"
            WHERE c.slug = %s
            ORDER BY t.slug, b."order"
            """,
            (course_slug,),
        )
        rows = cur.fetchall()

    by_topic: dict[str, list[dict]] = {}
    for topic_slug, block_id, order, group_id, edited in rows:
        by_topic.setdefault(topic_slug, []).append(
            {"id": block_id, "order": order, "group_id": group_id, "edited": edited}
        )

    failures: list[str] = []
    pinned_groups = 0
    for topic_slug, blocks in by_topic.items():
        group_ids = {
            b["group_id"]
            for b in blocks
            if b["group_id"] is not None and b["edited"]
        }
        for group_id in group_ids:
            pinned_groups += 1
            positions = [
                i for i, b in enumerate(blocks) if b["group_id"] == group_id
            ]
            expected = list(range(positions[0], positions[0] + len(positions)))
            if positions != expected:
                failures.append(
                    f"{topic_slug}/{group_id}: pinned group is not contiguous "
                    f"(positions {positions})"
                )

    return EvalCheck(
        "pinned_anchor_integrity",
        not failures,
        failures,
        {"topics_checked": len(by_topic), "pinned_groups": pinned_groups},
    )


def _check_prereq_cycles_absent(course_slug: str) -> EvalCheck:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT from_t.id, to_t.id, from_t.slug, to_t.slug
            FROM "TopicEdge" e
            JOIN "Topic" from_t ON from_t.id = e."fromId"
            JOIN "Topic" to_t ON to_t.id = e."toId"
            JOIN "Course" c ON c.id = to_t."courseId"
            WHERE c.slug = %s
              AND from_t."courseId" = to_t."courseId"
              AND e.kind = 'PREREQUISITE_OF'
            """,
            (course_slug,),
        )
        rows = cur.fetchall()
    edges = [Edge(from_id=r[0], to_id=r[1], confidence=1.0, reason="eval") for r in rows]
    cycle = detect_cycle(edges)
    failures: list[str] = []
    if cycle:
        id_to_slug = {r[0]: r[2] for r in rows} | {r[1]: r[3] for r in rows}
        failures.append(" -> ".join(id_to_slug.get(i, i) for i in cycle))
    return EvalCheck(
        "prerequisite_cycles_absent",
        not failures,
        failures,
        {"edges_checked": len(edges)},
    )


def _check_known_bad_edges_excluded() -> EvalCheck:
    conn = db.get_conn()
    failures: list[str] = []
    with conn.cursor() as cur:
        for from_slug, to_slug in BAD_EDGES:
            cur.execute(
                """
                SELECT 1
                FROM "TopicEdge" e
                JOIN "Topic" from_t ON from_t.id = e."fromId"
                JOIN "Topic" to_t ON to_t.id = e."toId"
                WHERE from_t.slug = %s
                  AND to_t.slug = %s
                  AND e.kind = 'PREREQUISITE_OF'
                LIMIT 1
                """,
                (from_slug, to_slug),
            )
            if cur.fetchone():
                failures.append(f"{from_slug} -> {to_slug}")
    return EvalCheck(
        "known_bad_mapper_edges_excluded",
        not failures,
        failures,
        {"bad_edges_checked": len(BAD_EDGES)},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run content-generation evals.")
    parser.add_argument("--course", required=True)
    parser.add_argument("--weak-floor", type=float, default=0.70)
    parser.add_argument("--strong-floor", type=float, default=0.75)
    parser.add_argument("--strong-min", type=int, default=3)
    parser.add_argument("--k", type=int, default=8)
    args = parser.parse_args()

    try:
        report = run_content_generation_evals(
            args.course,
            weak_floor=args.weak_floor,
            strong_floor=args.strong_floor,
            strong_min=args.strong_min,
            k=args.k,
        )
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
        if not report.ok:
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
