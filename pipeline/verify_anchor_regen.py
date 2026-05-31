"""
pipeline/verify_anchor_regen.py

End-to-end verification of pinned-anchor regeneration on real topic data.
Tests the full chain: block_gen read -> prompt -> model output ->
anchor-integrity validation -> replace_topic_blocks.

Usage:
    # 1. Seed: pick blocks, mutate them, write snapshot
    python -m pipeline.verify_anchor_regen seed --topic <slug>

    # 2. Run generation (manually)
    python -m pipeline.block_gen --course <course-slug> --topic <slug>

    # 3. Verify preservation
    python -m pipeline.verify_anchor_regen verify --topic <slug>

    # 4. (optional) undo seed mutations
    python -m pipeline.verify_anchor_regen cleanup --topic <slug>

The snapshot file defaults to .verify_<slug>.json in the cwd.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import uuid
from typing import Any

from pipeline import db


def _snapshot_path(topic_slug: str, override: str | None) -> pathlib.Path:
    return pathlib.Path(override) if override else pathlib.Path(f".verify_{topic_slug}.json")


def _resolve_topic(slug: str) -> tuple[str, str]:
    """Return (topic_id, course_slug). Fail loud if not found."""
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT t.id, c.slug
            FROM "Topic" t JOIN "Course" c ON c.id = t."courseId"
            WHERE t.slug = %s
            ''',
            (slug,),
        )
        row = cur.fetchone()
    if not row:
        sys.exit(f"no topic with slug={slug!r}")
    return row[0], row[1]


def _fetch_blocks(topic_id: str) -> list[dict]:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT id, type, content, "order", manually_edited, group_id
            FROM "Block"
            WHERE "topicId" = %s
            ORDER BY "order"
            ''',
            (topic_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _mutate_content(content: dict, marker: str) -> dict:
    """Type-agnostic content mutation. Inserts a marker that the
    anchor-integrity validator will require the model to reproduce
    byte-identically."""
    new = json.loads(json.dumps(content))  # deep copy
    new["_verify_marker"] = marker
    return new


def _pick_ungrouped(blocks: list[dict]) -> dict | None:
    return next((b for b in blocks if b["group_id"] is None), None)


def _pick_grouped_cohort(blocks: list[dict]) -> list[dict]:
    """Return all blocks of the first group_id encountered, or []."""
    by_group: dict[str, list[dict]] = {}
    for b in blocks:
        if b["group_id"] is not None:
            by_group.setdefault(b["group_id"], []).append(b)
    if not by_group:
        return []
    first_gid = next(iter(by_group))
    return sorted(by_group[first_gid], key=lambda b: b["order"])


def _update_block(block_id: str, content: dict, manually_edited: bool) -> None:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            '''
            UPDATE "Block"
            SET content = %s::jsonb, manually_edited = %s, "updatedAt" = now()
            WHERE id = %s
            ''',
            (json.dumps(content), manually_edited, block_id),
        )
        if cur.rowcount != 1:
            conn.rollback()
            sys.exit(f"update affected {cur.rowcount} rows for id={block_id}")
    conn.commit()


# ---- commands -------------------------------------------------------------

def cmd_seed(topic_slug: str, snapshot_path: pathlib.Path) -> None:
    if snapshot_path.exists():
        sys.exit(f"snapshot already exists at {snapshot_path}; cleanup first or pass --snapshot")

    topic_id, course_slug = _resolve_topic(topic_slug)
    blocks = _fetch_blocks(topic_id)
    if not blocks:
        sys.exit(f"topic {topic_slug!r} has no blocks; run block_gen first")

    ungrouped = _pick_ungrouped(blocks)
    cohort = _pick_grouped_cohort(blocks)

    if not ungrouped:
        sys.exit("no ungrouped block on this topic; pick a different topic")
    if not cohort:
        sys.exit("no grouped cohort on this topic; pick a different topic to test the atomic-group rule")

    cohort_target = cohort[0]  # mutate one member; per atomic rule, all should survive
    marker_u = f"verify-ungrouped-{uuid.uuid4().hex[:12]}"
    marker_g = f"verify-grouped-{uuid.uuid4().hex[:12]}"

    new_u_content = _mutate_content(ungrouped["content"], marker_u)
    new_g_content = _mutate_content(cohort_target["content"], marker_g)

    snapshot = {
        "topic_id": topic_id,
        "topic_slug": topic_slug,
        "course_slug": course_slug,
        "ungrouped": {
            "id": ungrouped["id"],
            "order_before": ungrouped["order"],
            "original_content": ungrouped["content"],
            "original_manually_edited": ungrouped["manually_edited"],
            "edited_content": new_u_content,
            "marker": marker_u,
        },
        "grouped": {
            "group_id": cohort_target["group_id"],
            "edited_block_id": cohort_target["id"],
            "edited_marker": marker_g,
            "cohort": [
                {
                    "id": b["id"],
                    "order_before": b["order"],
                    "content_before": (
                        new_g_content if b["id"] == cohort_target["id"] else b["content"]
                    ),
                    "original_content": b["content"],
                    "original_manually_edited": b["manually_edited"],
                    "type": b["type"],
                }
                for b in cohort
            ],
        },
    }

    _update_block(ungrouped["id"], new_u_content, True)
    _update_block(cohort_target["id"], new_g_content, True)

    snapshot_path.write_text(json.dumps(snapshot, indent=2, default=str))

    print(f"seeded.")
    print(f"  ungrouped: id={ungrouped['id']} (type={ungrouped['type']}) flag->true, marker={marker_u}")
    print(f"  grouped:   group_id={cohort_target['group_id']} ({len(cohort)} members)")
    print(f"             edited member id={cohort_target['id']} (type={cohort_target['type']}) flag->true, marker={marker_g}")
    print(f"             remaining cohort members ({len(cohort) - 1}): unchanged on disk; should still survive via atomic expansion")
    print(f"  snapshot:  {snapshot_path}")
    print()
    print(f"next: python -m pipeline.block_gen --course {course_slug} --topic {topic_slug}")


def _diff(label: str, expected: Any, got: Any) -> list[str]:
    if expected == got:
        return []
    return [f"  FAIL {label}:\n    expected: {json.dumps(expected, default=str)}\n    got:      {json.dumps(got, default=str)}"]


def cmd_verify(topic_slug: str, snapshot_path: pathlib.Path) -> None:
    if not snapshot_path.exists():
        sys.exit(f"no snapshot at {snapshot_path}; run seed first")
    snap = json.loads(snapshot_path.read_text())
    topic_id = snap["topic_id"]

    blocks = _fetch_blocks(topic_id)
    by_id = {b["id"]: b for b in blocks}
    failures: list[str] = []

    # ---- ungrouped anchor ----
    u = snap["ungrouped"]
    got_u = by_id.get(u["id"])
    if got_u is None:
        failures.append(f"  FAIL ungrouped: id {u['id']} missing from topic after regen")
    else:
        failures += _diff("ungrouped.content (must be byte-identical to edited_content)",
                          u["edited_content"], got_u["content"])
        failures += _diff("ungrouped.manually_edited", True, got_u["manually_edited"])
        failures += _diff("ungrouped.group_id", None, got_u["group_id"])

    # ---- grouped cohort ----
    g = snap["grouped"]
    cohort_ids = [m["id"] for m in g["cohort"]]
    got_cohort = [by_id.get(i) for i in cohort_ids]
    if any(b is None for b in got_cohort):
        missing = [i for i, b in zip(cohort_ids, got_cohort) if b is None]
        failures.append(f"  FAIL grouped: cohort members missing after regen: {missing}")
    else:
        # every member preserved with same group_id and same content
        for member, got in zip(g["cohort"], got_cohort):
            label = f"grouped.cohort[id={member['id']}]"
            failures += _diff(f"{label}.content", member["content_before"], got["content"])
            failures += _diff(f"{label}.group_id", g["group_id"], got["group_id"])
            # internal relative order preserved
        got_orders = [b["order"] for b in got_cohort]
        if got_orders != sorted(got_orders):
            failures.append(f"  FAIL grouped: cohort internal order broken; got orders {got_orders}")
        # contiguous in final sequence?
        all_orders_sorted = sorted(b["order"] for b in blocks)
        cohort_orders = sorted(got_orders)
        idx0 = all_orders_sorted.index(cohort_orders[0])
        expected_slots = all_orders_sorted[idx0:idx0 + len(cohort_orders)]
        if expected_slots != cohort_orders:
            failures.append(
                f"  FAIL grouped: cohort not contiguous in final sequence; "
                f"cohort_orders={cohort_orders}, surrounding slots={expected_slots}"
            )
        # the edited member's manually_edited flag should still be true
        edited_got = by_id[g["edited_block_id"]]
        failures += _diff("grouped.edited_member.manually_edited", True, edited_got["manually_edited"])

    if failures:
        print("VERIFY FAILED")
        for line in failures:
            print(line)
        sys.exit(1)

    total = len(blocks)
    n_pinned = 1 + len(g["cohort"])
    print(f"VERIFY OK")
    print(f"  ungrouped anchor preserved (id, content, flag, group_id)")
    print(f"  grouped cohort of {len(g['cohort'])} preserved atomically (ids, contents, group_id, internal order, contiguity)")
    print(f"  topic has {total} blocks total ({n_pinned} pinned, {total - n_pinned} regenerated)")


def cmd_cleanup(topic_slug: str, snapshot_path: pathlib.Path) -> None:
    if not snapshot_path.exists():
        sys.exit(f"no snapshot at {snapshot_path}")
    snap = json.loads(snapshot_path.read_text())

    u = snap["ungrouped"]
    _update_block(u["id"], u["original_content"], u["original_manually_edited"])

    g = snap["grouped"]
    edited_id = g["edited_block_id"]
    edited_member = next(m for m in g["cohort"] if m["id"] == edited_id)
    _update_block(edited_id, edited_member["original_content"], edited_member["original_manually_edited"])

    snapshot_path.unlink()
    print(f"reverted ungrouped id={u['id']} and grouped id={edited_id}; removed {snapshot_path}")


# ---- CLI ------------------------------------------------------------------

def _main() -> None:
    p = argparse.ArgumentParser(description="Verify pinned-anchor regeneration end-to-end.")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("seed", "verify", "cleanup"):
        sp = sub.add_parser(name)
        sp.add_argument("--topic", required=True, help="topic slug")
        sp.add_argument("--snapshot", help="snapshot path (default: .verify_<slug>.json)")
    args = p.parse_args()

    snapshot_path = _snapshot_path(args.topic, args.snapshot)
    try:
        {"seed": cmd_seed, "verify": cmd_verify, "cleanup": cmd_cleanup}[args.cmd](args.topic, snapshot_path)
    finally:
        db.close()


if __name__ == "__main__":
    _main()