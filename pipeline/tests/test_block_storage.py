"""
Focused regressions for Agent 3 storage and pinned-anchor shape.

These are pure-function tests: no DB and no LLM.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pipeline.anchor_integrity import validate_anchor_integrity
from pipeline.orchestrator import (
    _apply_context_fingerprint,
    _filter_source_chunk_ids,
    _to_reconciler_shape,
    _to_storage_content,
    _validate,
)


@dataclass(frozen=True)
class _Blk:
    id: str
    type: str
    content: dict
    group_id: Optional[str]


@dataclass(frozen=True)
class _Cohort:
    group_id: Optional[str]
    blocks: tuple[_Blk, ...]
    pinned: bool = True


def test_to_storage_content_persists_blocknote_shape():
    block = {
        "type": "heading",
        "content": [{"type": "text", "text": "Critical points"}],
        "props": {"level": 2},
        "generation_metadata": {"source_chunk_ids": ["chunk_1"]},
        "group_id": "grp_ignored_by_content",
    }

    assert _to_storage_content(block) == {
        "type": "heading",
        "content": [{"type": "text", "text": "Critical points"}],
        "props": {"level": 2},
    }


def test_to_reconciler_shape_keeps_pinned_refs_and_stores_new_blocknote_content():
    blocks = [
        {
            "id": "pinned_1",
            "type": "paragraph",
            "content": {
                "type": "paragraph",
                "content": [{"type": "text", "text": "User edited."}],
            },
            "group_id": None,
        },
        {
            "type": "math",
            "content": [],
            "props": {"mode": "display", "latex": r"\nabla f = \lambda \nabla g"},
            "generation_metadata": {"source_chunk_ids": ["chunk_web"]},
        },
    ]

    pinned_ids, sequence = _to_reconciler_shape(blocks, "test-model")

    assert pinned_ids == ["pinned_1"]
    assert sequence[0] == {"id": "pinned_1"}
    assert sequence[1]["type"] == "math"
    assert sequence[1]["content"] == {
        "type": "math",
        "content": [],
        "props": {"mode": "display", "latex": r"\nabla f = \lambda \nabla g"},
    }
    assert sequence[1]["generation_metadata"]["source_chunk_ids"] == ["chunk_web"]
    assert sequence[1]["generation_metadata"]["agent"] == "agent3"
    assert (
        sequence[1]["generation_metadata"]["output_format_version"]
        == "agent3.block-output.v1"
    )
    assert sequence[1]["generation_metadata"]["decoding"] == {
        "max_tokens": 20000,
        "temperature": 0,
    }


def test_apply_context_fingerprint_marks_generated_blocks_only():
    sequence = [
        {"id": "pinned_1"},
        {
            "type": "paragraph",
            "content": {"type": "paragraph", "content": []},
            "generation_metadata": {"source_chunk_ids": []},
        },
    ]

    _apply_context_fingerprint(sequence, "ctx_123")

    assert "generation_metadata" not in sequence[0]
    assert sequence[1]["generation_metadata"]["context_fingerprint"] == "ctx_123"


def test_pinned_anchor_accepts_persisted_object_content_without_normalizing():
    stored_content = {
        "type": "paragraph",
        "content": [
            {"type": "text", "text": "The constraint curve is the anchor."}
        ],
        "props": {"textAlignment": "left"},
    }
    blk = _Blk("anchor_obj", "paragraph", stored_content, None)
    cohort = _Cohort(None, (blk,))

    emitted = {
        "id": "anchor_obj",
        "type": "paragraph",
        "content": {
            "props": {"textAlignment": "left"},
            "content": [
                {"text": "The constraint curve is the anchor.", "type": "text"}
            ],
            "type": "paragraph",
        },
        "group_id": None,
    }

    assert validate_anchor_integrity([emitted], [cohort]) == []


def test_pinned_image_anchor_survives_reconciler_shape():
    stored_content = {
        "type": "image",
        "content": [],
        "props": {
            "src": "https://example.com/surface.png",
            "alt": "A labeled surface.",
            "caption": "Uploaded by the editor.",
        },
    }
    blocks = [
        {
            "id": "image_anchor",
            "type": "image",
            "content": stored_content,
            "group_id": None,
        },
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Generated text."}],
            "generation_metadata": {"source_chunk_ids": []},
        },
    ]

    pinned_ids, sequence = _to_reconciler_shape(blocks, "test-model")

    assert pinned_ids == ["image_anchor"]
    assert sequence[0] == {"id": "image_anchor"}
    assert sequence[1]["type"] == "paragraph"


def test_validate_rejects_unknown_source_chunk_ids():
    blocks = [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Grounded sentence."}],
            "generation_metadata": {"source_chunk_ids": ["chunk_real", "chunk_fake"]},
        }
    ]

    errors = _validate(blocks, [], {"chunk_real"})

    assert errors
    assert "chunk_fake" in " ".join(errors)


def test_filter_source_chunk_ids_drops_unknown_ids_before_validation():
    blocks = [
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Grounded sentence."}],
            "generation_metadata": {
                "source_chunk_ids": ["chunk_real", "chunk_fake", "chunk_other"]
            },
        }
    ]

    _filter_source_chunk_ids(blocks, {"chunk_real", "chunk_other"})

    assert blocks[0]["generation_metadata"]["source_chunk_ids"] == [
        "chunk_real",
        "chunk_other",
    ]
    assert _validate(blocks, [], {"chunk_real", "chunk_other"}) == []


def test_validate_rejects_agent3_generated_image_blocks():
    blocks = [
        {
            "type": "image",
            "content": [],
            "props": {"src": "https://example.com/x.png", "alt": "Example"},
            "generation_metadata": {"source_chunk_ids": []},
        }
    ]

    errors = _validate(blocks, [], set())

    assert errors
    assert "Agent 3 must not emit image blocks" in " ".join(errors)
