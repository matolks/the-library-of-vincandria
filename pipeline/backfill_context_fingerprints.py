"""
Backfill Agent 3 context fingerprints for pre-rollout generated blocks.

This is an explicit production rollout tool, not part of the migration. Running
it with --apply means: "accept the current generated blocks as the baseline for
change-aware reruns." The default dry run only classifies what would happen.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable

from pipeline import db
from pipeline.block_gen import (
    ExistingBlock,
    agent3_generation_config,
    compute_context_fingerprint,
    get_topic_context,
)
from pipeline.db_guard import ensure_writable


BACKFILL_POLICY_VERSION = "context-fingerprint-backfill.v1"


@dataclass(frozen=True)
class BackfillDecision:
    topic_id: str
    slug: str
    status: str
    reason: str
    expected_fingerprint: str | None
    blocks_to_update: int
    total_blocks: int
    manually_edited_blocks: int
    stored_fingerprints: tuple[str, ...] = ()


def classify_topic(
    topic_id: str,
    *,
    generation_config: dict | None = None,
) -> tuple[BackfillDecision, tuple[str, ...]]:
    """Return the backfill decision and generated block ids to update."""
    context = get_topic_context(topic_id)
    generation_config = generation_config or agent3_generation_config()
    blocks = tuple(block for cohort in context.cohorts for block in cohort.blocks)
    generated_blocks = tuple(
        block for block in blocks if not block.manually_edited
    )
    stored = _stored_fingerprints(blocks)
    manual_count = sum(1 for block in blocks if block.manually_edited)

    if not blocks:
        return (
            BackfillDecision(
                topic_id,
                context.topic.slug,
                "skipped",
                "no_blocks",
                None,
                0,
                0,
                0,
                stored,
            ),
            (),
        )

    expected = compute_context_fingerprint(
        context,
        generation_config=generation_config,
    )
    if expected in stored:
        return (
            BackfillDecision(
                topic_id,
                context.topic.slug,
                "skipped",
                "already_current",
                expected,
                0,
                len(blocks),
                manual_count,
                stored,
            ),
            (),
        )

    if stored:
        return (
            BackfillDecision(
                topic_id,
                context.topic.slug,
                "needs_regeneration",
                "stored_fingerprint_mismatch",
                expected,
                0,
                len(blocks),
                manual_count,
                stored,
            ),
            (),
        )

    block_ids = tuple(block.id for block in generated_blocks)
    return (
        BackfillDecision(
            topic_id,
            context.topic.slug,
            "would_backfill",
            "missing_context_fingerprint",
            expected,
            len(block_ids),
            len(blocks),
            manual_count,
            stored,
        ),
        block_ids,
    )


def apply_backfill(
    block_ids: Iterable[str],
    *,
    context_fingerprint: str,
    backfilled_at: str | None = None,
) -> int:
    block_ids = tuple(block_ids)
    if not block_ids:
        return 0
    ensure_writable()
    backfilled_at = backfilled_at or datetime.now(timezone.utc).isoformat()
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE "Block"
            SET generation_metadata =
                    COALESCE(generation_metadata, '{}'::jsonb)
                    || %s::jsonb,
                "updatedAt" = now()
            WHERE id = ANY(%s)
              AND manually_edited = false
            """,
            (
                json.dumps(
                    {
                        "context_fingerprint": context_fingerprint,
                        "context_fingerprint_backfilled_at": backfilled_at,
                        "context_fingerprint_backfill_policy": BACKFILL_POLICY_VERSION,
                    }
                ),
                list(block_ids),
            ),
        )
        updated = cur.rowcount
    conn.commit()
    return updated


def _stored_fingerprints(blocks: Iterable[ExistingBlock]) -> tuple[str, ...]:
    return tuple(sorted({
        block.generation_metadata.get("context_fingerprint")
        for block in blocks
        if isinstance(block.generation_metadata, dict)
        and block.generation_metadata.get("context_fingerprint")
    }))


def _resolve_targets(course_slug: str, topic_slug: str | None) -> list[tuple[str, str]]:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.slug
            FROM "Topic" t
            JOIN "Course" c ON c.id = t."courseId"
            WHERE c.slug = %s
              AND (%s::text IS NULL OR t.slug = %s)
            ORDER BY t."order"
            """,
            (course_slug, topic_slug, topic_slug),
        )
        rows = cur.fetchall()
    if not rows:
        raise SystemExit(
            f"No topics found for course={course_slug!r}"
            + (f" topic={topic_slug!r}" if topic_slug else "")
        )
    return [(row[0], row[1]) for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dry-run or apply Agent 3 context-fingerprint backfill."
    )
    parser.add_argument("--course", required=True)
    parser.add_argument("--topic", help="optional topic slug")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--model", help="Agent 3 model to baseline")
    parser.add_argument("--max-tokens", type=int, default=20000)
    parser.add_argument("--temperature", type=float, default=0)
    args = parser.parse_args()

    generation_config = agent3_generation_config(
        model=args.model,
        max_tokens=args.max_tokens,
        temperature=args.temperature,
    )
    totals: dict[str, int] = {}
    try:
        for topic_id, _slug in _resolve_targets(args.course, args.topic):
            decision, block_ids = classify_topic(
                topic_id,
                generation_config=generation_config,
            )
            updated = 0
            if args.apply and decision.status == "would_backfill":
                if decision.expected_fingerprint is None:
                    raise RuntimeError("would_backfill without expected fingerprint")
                updated = apply_backfill(
                    block_ids,
                    context_fingerprint=decision.expected_fingerprint,
                )
            totals[decision.status] = totals.get(decision.status, 0) + 1
            print(json.dumps({**asdict(decision), "updated": updated}, sort_keys=True))
    finally:
        db.close()

    print("TOTAL:", json.dumps(totals, sort_keys=True))


if __name__ == "__main__":
    main()
