"""
Anchor integrity validation for generated block sequences.

Pure function: (sequence, pinned_cohorts) -> list[str]. Empty list means
every anchor was preserved per contract 1 (relative-order pinning) and
contract 2 (atomic group coupling).

Scope:
- Every anchor in pinned_cohorts appears in sequence exactly once.
- Anchor `id` matches; `content` byte-identical (canonicalized JSON compare).
- Grouped anchors contiguous in original internal order.
- Relative order of anchors preserved across the sequence.

Out of scope:
- Per-block schema (validate_block_schema).
- DB-level pinned-id existence (the reconciler checks).
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.block_gen import BlockCohort


def validate_anchor_integrity(
    sequence: list[dict],
    pinned_cohorts: "list[BlockCohort]",
) -> list[str]:
    """Return [] if anchors are preserved per contracts 1 and 2."""
    errs: list[str] = []

    # Build expected-anchor index from cohorts (already filtered to .pinned upstream).
    expected_by_id: dict[str, dict] = {}      # id -> original block dict-shape view
    expected_order: list[str] = []            # anchor ids in original relative order
    cohort_of: dict[str, int] = {}            # anchor id -> cohort index
    cohort_internal_order: dict[str, int] = {}  # anchor id -> position within its cohort

    for ci, cohort in enumerate(pinned_cohorts):
        for pi, blk in enumerate(cohort.blocks):
            expected_by_id[blk.id] = {
                "id": blk.id,
                "type": blk.type,
                "content": blk.content,
                "group_id": blk.group_id,
            }
            expected_order.append(blk.id)
            cohort_of[blk.id] = ci
            cohort_internal_order[blk.id] = pi

    # Walk sequence: find every item that carries an id, treat as anchor claim.
    seen_ids: list[str] = []
    seen_positions: dict[str, int] = {}
    for si, item in enumerate(sequence):
        if not isinstance(item, dict):
            continue  # schema validator catches non-dicts; skip here
        item_id = item.get("id")
        if item_id is None:
            continue
        if item_id in seen_positions:
            errs.append(
                f"sequence[{si}]: anchor id {item_id!r} appears more than once "
                f"(first at sequence[{seen_positions[item_id]}])"
            )
            continue
        seen_positions[item_id] = si
        seen_ids.append(item_id)

        if item_id not in expected_by_id:
            errs.append(
                f"sequence[{si}]: anchor id {item_id!r} is not in pinned_cohorts; "
                f"only pinned blocks may carry an `id`"
            )
            continue

        exp = expected_by_id[item_id]
        if item.get("type") != exp["type"]:
            errs.append(
                f"sequence[{si}] (anchor {item_id!r}): type changed from "
                f"{exp['type']!r} to {item.get('type')!r}; anchors are immutable"
            )
        if not _content_equal(item.get("content"), exp["content"]):
            errs.append(
                f"sequence[{si}] (anchor {item_id!r}): content was modified; "
                f"anchor content must be byte-identical to the value in PINNED ANCHORS"
            )
        item_gid = item.get("group_id")
        if item_gid != exp["group_id"]:
            errs.append(
                f"sequence[{si}] (anchor {item_id!r}): group_id changed from "
                f"{exp['group_id']!r} to {item_gid!r}; anchors are immutable"
            )

    # Missing anchors
    missing = [aid for aid in expected_order if aid not in seen_positions]
    for aid in missing:
        errs.append(
            f"anchor {aid!r} is missing from sequence; every pinned anchor must appear"
        )

    # Drop unrecognized/missing/duplicate anchors before order/contiguity checks
    valid_seen = [aid for aid in seen_ids if aid in expected_by_id]

    # Relative order
    valid_expected = [aid for aid in expected_order if aid in valid_seen]
    if valid_seen != valid_expected:
        errs.append(
            f"anchors out of relative order: sequence has {valid_seen}, "
            f"expected relative order {valid_expected}"
        )

    # Group contiguity + internal order. For each multi-block cohort, verify
    # its anchors occupy consecutive sequence indices in original internal order.
    for cohort in pinned_cohorts:
        if len(cohort.blocks) < 2:
            continue
        member_ids = [b.id for b in cohort.blocks]
        positions = [seen_positions.get(aid) for aid in member_ids]
        if any(p is None for p in positions):
            continue  # missing anchor already reported above
        expected_positions = list(range(positions[0], positions[0] + len(member_ids)))
        if positions != expected_positions:
            errs.append(
                f"cohort group_id={cohort.group_id!r} broken: members must be "
                f"contiguous in original internal order; got sequence positions "
                f"{positions} for members {member_ids}"
            )
    return errs


def _content_equal(a, b) -> bool:
    """Canonicalized JSON comparison: handles dict key ordering."""
    try:
        return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    except (TypeError, ValueError):
        return False