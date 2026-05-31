"""
Focused regression for the course-level orchestrator.

No DB, chunker, or LLM calls: stage functions are monkeypatched so the test
only verifies sequencing and aggregate status/token/cost reporting.
"""
from __future__ import annotations

from pipeline import course_orchestrator as orch


def test_course_pipeline_chains_stages_and_aggregates(monkeypatch):
    calls: list[str] = []

    def fake_load_chunks(course_slug, *, skip_chunker, chunk_file):
        calls.append("chunker")
        assert course_slug == "multivariable-calculus"
        assert skip_chunker is True
        assert chunk_file is None
        return [{"chunk_index": 0}]

    def fake_extractor(course_slug, chunks, *, dry_run):
        calls.append("extractor")
        assert chunks == [{"chunk_index": 0}]
        assert dry_run is True
        return (
            orch.StageReport(
                "extractor",
                "dry_run",
                input_tokens=10,
                output_tokens=20,
                usd_cost=0.30,
            ),
            {"topic-a": "topic-id-a"},
        )

    def fake_mapper(course_slug, *, dry_run):
        calls.append("mapper")
        return orch.StageReport(
            "mapper",
            "dry_run",
            input_tokens=30,
            output_tokens=40,
            usd_cost=0.70,
        )

    def fake_enricher(course_slug, *, include_thin, dry_run):
        calls.append("enricher")
        assert include_thin is True
        return orch.StageReport("enricher", "dry_run")

    def fake_block_gen(course_slug, *, dry_run):
        calls.append("block_gen")
        return orch.StageReport(
            "block_gen",
            "dry_run",
            input_tokens=50,
            output_tokens=60,
            cache_creation_tokens=70,
            cache_read_tokens=80,
            usd_cost=0.90,
        )

    monkeypatch.setattr(orch, "_load_chunks", fake_load_chunks)
    monkeypatch.setattr(orch, "_run_extractor", fake_extractor)
    monkeypatch.setattr(orch, "_run_mapper", fake_mapper)
    monkeypatch.setattr(orch, "_run_enricher", fake_enricher)
    monkeypatch.setattr(orch, "_run_block_gen", fake_block_gen)

    report = orch.run_course_pipeline(
        "multivariable-calculus",
        dry_run=True,
        include_thin=True,
        skip_chunker=True,
    )

    assert calls == ["chunker", "extractor", "mapper", "enricher", "block_gen"]
    assert report.status == "ok"
    assert report.input_tokens == 90
    assert report.output_tokens == 120
    assert report.cache_creation_tokens == 70
    assert report.cache_read_tokens == 80
    assert report.usd_cost == 1.90
