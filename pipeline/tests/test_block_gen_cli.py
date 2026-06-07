from __future__ import annotations

from pathlib import Path

import pytest

from pipeline import block_gen as bg
from pipeline.block_gen import (
    _load_topic_slugs_file,
    _normalize_topic_filters,
    MapperReadiness,
)


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


def test_get_mapper_readiness_detects_fingerprint_mismatch(monkeypatch):
    monkeypatch.setattr(bg.db, "get_course_id", lambda slug: "course-id")

    class FakeMapper:
        @staticmethod
        def get_course_topics(course_slug):
            return "course-id", [{"slug": "topic-a", "title": "Topic A", "summary": None}]

        @staticmethod
        def compute_fingerprint(topics):
            return "expected-fingerprint"

    monkeypatch.setattr("pipeline.mapper.get_course_topics", FakeMapper.get_course_topics)
    monkeypatch.setattr("pipeline.mapper.compute_fingerprint", FakeMapper.compute_fingerprint)
    monkeypatch.setattr(
        bg.db,
        "get_pipeline_state",
        lambda *args, **kwargs: {
            "fingerprint": "stale-fingerprint",
            "status": "ok",
            "metadata": None,
            "updatedAt": None,
        },
    )

    readiness = bg.get_mapper_readiness("operating-systems")

    assert readiness == MapperReadiness(
        False,
        "fingerprint_mismatch",
        expected_fingerprint="expected-fingerprint",
        actual_fingerprint="stale-fingerprint",
        actual_status="ok",
    )


def test_ensure_mapper_ready_for_block_gen_requires_override(monkeypatch):
    monkeypatch.setattr(
        bg,
        "get_mapper_readiness",
        lambda course_slug: MapperReadiness(False, "status_not_ok", actual_status="failed"),
    )

    with pytest.raises(SystemExit, match="allow-degraded-mapper"):
        bg.ensure_mapper_ready_for_block_gen("operating-systems")

    bg.ensure_mapper_ready_for_block_gen(
        "operating-systems",
        allow_degraded_mapper=True,
    )
