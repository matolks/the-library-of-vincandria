"""
Unit tests for validate_anchor_integrity.

Hand-crafted sequences and cohorts. No DB, no LLM.

Run:
  pytest pipeline/tests/test_anchor_integrity.py -v
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from pipeline.anchor_integrity import validate_anchor_integrity


# Mirror the relevant fields of ExistingBlock / BlockCohort so tests don't
# require importing the real dataclasses (and don't drift if those change
# in ways unrelated to anchor integrity).
@dataclass(frozen=True)
class _Blk:
    id: str
    type: str
    content: dict
    group_id: Optional[str]
    order: int = 0
    manually_edited: bool = True
    generation_metadata: Optional[dict] = None


@dataclass(frozen=True)
class _Cohort:
    group_id: Optional[str]
    blocks: tuple
    pinned: bool = True


def _anchor_item(blk: _Blk) -> dict:
    """Build the dict-shape the model is supposed to emit for an anchor."""
    return {
        "id": blk.id,
        "type": blk.type,
        "content": blk.content,
        "group_id": blk.group_id,
    }


def _new_block(text: str) -> dict:
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


# ---- success cases --------------------------------------------------------


def test_no_anchors_no_errors():
    seq = [_new_block("a"), _new_block("b")]
    assert validate_anchor_integrity(seq, []) == []


def test_singleton_anchor_preserved():
    blk = _Blk("blk_1", "paragraph", {"text": "x"}, None)
    cohort = _Cohort(None, (blk,))
    seq = [_new_block("intro"), _anchor_item(blk), _new_block("outro")]
    assert validate_anchor_integrity(seq, [cohort]) == []


def test_grouped_anchor_contiguous_in_order():
    b1 = _Blk("blk_g1", "math", {"latex": "x^2"}, "grp1")
    b2 = _Blk("blk_g2", "paragraph", {"text": "explanation"}, "grp1")
    cohort = _Cohort("grp1", (b1, b2))
    seq = [_new_block("lead"), _anchor_item(b1), _anchor_item(b2), _new_block("tail")]
    assert validate_anchor_integrity(seq, [cohort]) == []


def test_two_cohorts_relative_order_preserved():
    a = _Blk("blk_a", "paragraph", {"text": "a"}, None)
    b = _Blk("blk_b", "paragraph", {"text": "b"}, None)
    seq = [_anchor_item(a), _new_block("mid"), _anchor_item(b)]
    assert validate_anchor_integrity(seq, [_Cohort(None, (a,)), _Cohort(None, (b,))]) == []


def test_content_canonicalized_key_order():
    """Reordered dict keys must compare equal."""
    blk = _Blk("blk_x", "math", {"a": 1, "b": 2}, None)
    cohort = _Cohort(None, (blk,))
    # Model emits same content with swapped key order
    emitted = {"id": "blk_x", "type": "math", "content": {"b": 2, "a": 1}, "group_id": None}
    assert validate_anchor_integrity([emitted], [cohort]) == []


# ---- failure cases --------------------------------------------------------


def test_missing_anchor():
    blk = _Blk("blk_1", "paragraph", {"text": "x"}, None)
    cohort = _Cohort(None, (blk,))
    seq = [_new_block("only new content")]
    errs = validate_anchor_integrity(seq, [cohort])
    assert any("'blk_1' is missing from sequence" in e for e in errs)


def test_duplicate_anchor_ref():
    blk = _Blk("blk_1", "paragraph", {"text": "x"}, None)
    cohort = _Cohort(None, (blk,))
    seq = [_anchor_item(blk), _new_block("mid"), _anchor_item(blk)]
    errs = validate_anchor_integrity(seq, [cohort])
    assert any("appears more than once" in e for e in errs)


def test_unrecognized_anchor_id():
    blk = _Blk("blk_real", "paragraph", {"text": "x"}, None)
    cohort = _Cohort(None, (blk,))
    seq = [
        _anchor_item(blk),
        {"id": "blk_ghost", "type": "paragraph", "content": {"text": "?"}, "group_id": None},
    ]
    errs = validate_anchor_integrity(seq, [cohort])
    assert any("'blk_ghost' is not in pinned_cohorts" in e for e in errs)


def test_anchor_content_mutated():
    blk = _Blk("blk_1", "paragraph", {"text": "original"}, None)
    cohort = _Cohort(None, (blk,))
    mutated = {"id": "blk_1", "type": "paragraph", "content": {"text": "tweaked"}, "group_id": None}
    errs = validate_anchor_integrity([mutated], [cohort])
    assert any("content was modified" in e for e in errs)


def test_anchor_type_changed():
    blk = _Blk("blk_1", "paragraph", {"text": "x"}, None)
    cohort = _Cohort(None, (blk,))
    bad = {"id": "blk_1", "type": "heading", "content": {"text": "x"}, "group_id": None}
    errs = validate_anchor_integrity([bad], [cohort])
    assert any("type changed" in e for e in errs)


def test_anchor_group_id_changed():
    blk = _Blk("blk_1", "paragraph", {"text": "x"}, "grp1")
    # Cohort still has the block under grp1; model strips group_id on emit
    cohort = _Cohort("grp1", (blk,))
    bad = {"id": "blk_1", "type": "paragraph", "content": {"text": "x"}, "group_id": None}
    errs = validate_anchor_integrity([bad], [cohort])
    assert any("group_id changed" in e for e in errs)


def test_relative_order_swapped():
    a = _Blk("blk_a", "paragraph", {"text": "a"}, None)
    b = _Blk("blk_b", "paragraph", {"text": "b"}, None)
    cohorts = [_Cohort(None, (a,)), _Cohort(None, (b,))]
    seq = [_anchor_item(b), _new_block("mid"), _anchor_item(a)]  # swapped
    errs = validate_anchor_integrity(seq, cohorts)
    assert any("out of relative order" in e for e in errs)


def test_group_split_by_new_block():
    b1 = _Blk("blk_g1", "math", {"latex": "x"}, "grp1")
    b2 = _Blk("blk_g2", "paragraph", {"text": "y"}, "grp1")
    cohort = _Cohort("grp1", (b1, b2))
    seq = [_anchor_item(b1), _new_block("intruder"), _anchor_item(b2)]
    errs = validate_anchor_integrity(seq, [cohort])
    assert any("cohort group_id='grp1' broken" in e for e in errs)


def test_group_internal_order_swapped():
    b1 = _Blk("blk_g1", "math", {"latex": "x"}, "grp1")
    b2 = _Blk("blk_g2", "paragraph", {"text": "y"}, "grp1")
    cohort = _Cohort("grp1", (b1, b2))
    seq = [_anchor_item(b2), _anchor_item(b1)]  # swapped within cohort
    errs = validate_anchor_integrity(seq, [cohort])
    # Could trip either the cohort-broken or the relative-order check (or both); either is acceptable
    assert errs, "expected some error for cohort internal reordering"