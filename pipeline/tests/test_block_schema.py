"""
Unit tests for validate_block_schema.

Hand-crafted good and bad blocks. No DB, no LLM — pure-function tests.

Run:
  pytest pipeline/tests/test_block_schema.py -v
"""
from __future__ import annotations

import pytest

from pipeline.block_schema import validate_block_schema


GOOD_BLOCKS = [
    {"type": "paragraph", "content": [{"type": "text", "text": "Hello."}]},
    {
        "type": "paragraph",
        "content": [
            {"type": "text", "text": "Consider "},
            {"type": "math", "props": {"latex": "x^2"}},
            {"type": "text", "text": "."},
        ],
    },
    {
        "type": "heading",
        "content": [{"type": "text", "text": "Intro"}],
        "props": {"level": 2},
    },
    {"type": "bulletListItem", "content": [{"type": "text", "text": "item"}]},
    {
        "type": "codeBlock",
        "content": [{"type": "text", "text": "print('hi')"}],
        "props": {"language": "python"},
    },
    {
        "type": "callout",
        "content": [{"type": "text", "text": "watch out"}],
        "props": {"variant": "warning"},
    },
    {
        "type": "math",
        "content": [],
        "props": {"mode": "display", "latex": r"\int_0^1 x\, dx"},
    },
    {
        "type": "plot",
        "content": [],
        "props": {
            "kind": "function2d",
            "expression": "x^2",
            "domain": {"x": [-2, 2]},
            "labels": {"x": "x", "y": "f(x)"},
        },
    },
    {
        "type": "plot",
        "content": [],
        "props": {
            "kind": "surface3d",
            "expression": "x^2 + y^2",
            "domain": {"x": [-2, 2], "y": [-2, 2]},
        },
    },
    {
        "type": "paragraph",
        "content": [{"type": "text", "text": "."}],
        "generation_metadata": {"source_chunk_ids": ["chunk_a", "chunk_b"]},
    },
    {
        "type": "paragraph",
        "content": [{"type": "text", "text": "."}],
        "generation_metadata": {"source_chunk_ids": []},
    },
]


@pytest.mark.parametrize(
    "block", GOOD_BLOCKS, ids=[f"good_{i:02d}" for i in range(len(GOOD_BLOCKS))]
)
def test_good_blocks_validate_cleanly(block):
    assert validate_block_schema(block) == []


BAD_CASES: list[tuple[str, dict, str]] = [
    ("unknown_type",
        {"type": "footnote", "content": []},
        "is not a valid BlockType"),
    ("heading_bad_level",
        {"type": "heading", "content": [{"type": "text", "text": "x"}], "props": {"level": 7}},
        "heading.props.level"),
    ("paragraph_content_not_array",
        {"type": "paragraph", "content": "Hello."},
        "must be an array of InlineContent"),
    ("inline_text_missing_text_field",
        {"type": "paragraph", "content": [{"type": "text"}]},
        "missing string `text`"),
    ("inline_math_missing_latex",
        {"type": "paragraph", "content": [{"type": "math", "props": {}}]},
        "inline math missing `props.latex`"),
    ("inline_math_has_dollar_delimiters",
        {"type": "paragraph", "content": [{"type": "math", "props": {"latex": "$x$"}}]},
        "without dollar delimiters"),
    ("inline_unknown_type",
        {"type": "paragraph", "content": [{"type": "video", "src": "x"}]},
        "unknown inline type"),
    ("code_block_empty_content",
        {"type": "codeBlock", "content": [], "props": {"language": "python"}},
        "single-element array"),
    ("code_block_missing_language",
        {"type": "codeBlock", "content": [{"type": "text", "text": "x"}], "props": {}},
        "codeBlock.props.language"),
    ("callout_bad_variant",
        {"type": "callout", "content": [{"type": "text", "text": "x"}], "props": {"variant": "danger"}},
        "callout.props.variant"),
    ("math_non_empty_content",
        {"type": "math", "content": [{"type": "text", "text": "x"}], "props": {"mode": "display", "latex": "x"}},
        "math.content must be an empty array"),
    ("math_missing_latex",
        {"type": "math", "content": [], "props": {"mode": "display", "latex": ""}},
        "math.props.latex"),
    ("math_has_dollar_delimiters",
        {"type": "math", "content": [], "props": {"mode": "display", "latex": "$x^2$"}},
        "without dollar delimiters"),
    ("plot_bad_kind",
        {"type": "plot", "content": [], "props": {"kind": "barchart", "expression": "x", "domain": {"x": [0, 1]}}},
        "plot.props.kind"),
    ("plot_function2d_missing_domain_x",
        {"type": "plot", "content": [], "props": {"kind": "function2d", "expression": "x^2", "domain": {"y": [-1, 1]}}},
        "missing required key(s) ['x']"),
    ("plot_surface3d_missing_y",
        {"type": "plot", "content": [], "props": {"kind": "surface3d", "expression": "x^2 + y^2", "domain": {"x": [-1, 1]}}},
        "missing required key(s) ['y']"),
    ("plot_bad_domain_range",
        {"type": "plot", "content": [], "props": {"kind": "function2d", "expression": "x", "domain": {"x": [2, 2]}}},
        "low < high"),
    ("generation_metadata_bad_chunk_id_type",
        {"type": "paragraph", "content": [{"type": "text", "text": "x"}],
         "generation_metadata": {"source_chunk_ids": [123]}},
        "must contain only strings"),
]


@pytest.mark.parametrize(
    "name, block, expected_substring",
    BAD_CASES,
    ids=[c[0] for c in BAD_CASES],
)
def test_bad_blocks_produce_matching_error(name, block, expected_substring):
    errs = validate_block_schema(block)
    assert errs, f"expected errors for {name}, got none"
    assert expected_substring in " ".join(errs), (
        f"for {name}: expected substring {expected_substring!r} in errors; got: {errs}"
    )
