from __future__ import annotations

from pathlib import Path

from pipeline.block_gen import _load_topic_slugs_file, _normalize_topic_filters


def test_normalize_topic_filters_dedupes_and_splits_commas():
    assert _normalize_topic_filters(
        "topic-a",
        ("topic-b, topic-c", "topic-b", "  ", "topic-d"),
    ) == ["topic-a", "topic-b", "topic-c", "topic-d"]


def test_load_topic_slugs_file_allows_comments_and_commas(tmp_path: Path):
    path = tmp_path / "topics.txt"
    path.write_text(
        """
        # affected MVC topics
        mvc-dot-product
        mvc-lines-planes-3d, mvc-parametric-curves # inline note

        mvc-arc-length
        """,
        encoding="utf-8",
    )

    assert _load_topic_slugs_file(str(path)) == (
        "mvc-dot-product",
        "mvc-lines-planes-3d",
        "mvc-parametric-curves",
        "mvc-arc-length",
    )
