"""
Focused regression for the course-level orchestrator.

No DB, chunker, or LLM calls: stage functions are monkeypatched so the test
only verifies sequencing and aggregate status/token/cost reporting.
"""
from __future__ import annotations

import pytest

from pipeline import course_orchestrator as orch
from pipeline.enricher import EnrichmentResult


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

    def fake_enricher(
        course_slug,
        *,
        include_thin,
        dry_run,
        force_all=False,
        course_id=None,
    ):
        calls.append("enricher")
        assert include_thin is True
        return orch.StageReport("enricher", "dry_run")

    def fake_block_gen(
        course_slug,
        *,
        dry_run,
        force_all=False,
        mapper_stage_status="ok",
        allow_degraded_mapper=False,
        model=None,
        max_tokens=None,
        temperature=None,
    ):
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

    monkeypatch.setattr(orch.db, "get_course_id", lambda course_slug: "course-id")
    monkeypatch.setattr(orch.db, "pipeline_state_matches", lambda *args, **kwargs: False)
    monkeypatch.setattr(orch, "_chunker_fingerprint", lambda *args, **kwargs: "chunker-fp")
    monkeypatch.setattr(orch, "_extractor_fingerprint", lambda *args, **kwargs: "extractor-fp")
    monkeypatch.setattr(orch, "_mapper_fingerprint", lambda *args, **kwargs: "mapper-fp")
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
    assert [stage.stage for stage in report.stages] == [
        "chunker",
        "extractor",
        "mapper",
        "enricher",
        "block_gen",
    ]
    assert report.input_tokens == 90
    assert report.output_tokens == 120
    assert report.cache_creation_tokens == 70
    assert report.cache_read_tokens == 80
    assert report.usd_cost == 1.90


def test_course_pipeline_skips_unchanged_course_stages(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(orch.db, "upsert_course", lambda *args, **kwargs: "course-id")
    monkeypatch.setattr(orch, "_chunker_fingerprint", lambda *args, **kwargs: "chunker-fp")
    monkeypatch.setattr(orch, "_extractor_fingerprint", lambda *args, **kwargs: "extractor-fp")
    monkeypatch.setattr(orch, "_mapper_fingerprint", lambda *args, **kwargs: "mapper-fp")
    monkeypatch.setattr(orch.db, "pipeline_state_matches", lambda *args, **kwargs: True)

    def fail_load_chunks(*args, **kwargs):
        raise AssertionError("chunker should be skipped")

    def fake_enricher(
        course_slug,
        *,
        include_thin,
        dry_run,
        force_all=False,
        course_id=None,
    ):
        calls.append("enricher")
        return orch.StageReport("enricher", "ok")

    def fake_block_gen(
        course_slug,
        *,
        dry_run,
        force_all=False,
        mapper_stage_status="ok",
        allow_degraded_mapper=False,
        model=None,
        max_tokens=None,
        temperature=None,
    ):
        calls.append("block_gen")
        return orch.StageReport("block_gen", "ok")

    monkeypatch.setattr(orch, "_load_chunks", fail_load_chunks)
    monkeypatch.setattr(orch, "_run_enricher", fake_enricher)
    monkeypatch.setattr(orch, "_run_block_gen", fake_block_gen)

    report = orch.run_course_pipeline("course-slug")

    assert calls == ["enricher", "block_gen"]
    assert report.status == "ok"
    assert [stage.status for stage in report.stages[:3]] == [
        "skipped",
        "skipped",
        "skipped",
    ]


def test_course_pipeline_force_all_bypasses_stage_fingerprint_skips(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(orch.db, "upsert_course", lambda *args, **kwargs: "course-id")
    monkeypatch.setattr(orch.db, "upsert_pipeline_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(orch, "_chunker_fingerprint", lambda *args, **kwargs: "chunker-fp")
    monkeypatch.setattr(orch, "_extractor_fingerprint", lambda *args, **kwargs: "extractor-fp")
    monkeypatch.setattr(orch, "_mapper_fingerprint", lambda *args, **kwargs: "mapper-fp")
    monkeypatch.setattr(orch.db, "pipeline_state_matches", lambda *args, **kwargs: True)

    def fake_load_chunks(course_slug, *, skip_chunker, chunk_file):
        calls.append("chunker")
        return [{"chunk_index": 0}]

    def fake_extractor(course_slug, chunks, *, dry_run):
        calls.append("extractor")
        return orch.StageReport("extractor", "ok"), {"topic-a": "topic-id-a"}

    def fake_mapper(course_slug, *, dry_run):
        calls.append("mapper")
        return orch.StageReport("mapper", "ok")

    def fake_enricher(
        course_slug,
        *,
        include_thin,
        dry_run,
        force_all=False,
        course_id=None,
    ):
        calls.append("enricher")
        return orch.StageReport("enricher", "ok")

    def fake_block_gen(
        course_slug,
        *,
        dry_run,
        force_all=False,
        mapper_stage_status="ok",
        allow_degraded_mapper=False,
        model=None,
        max_tokens=None,
        temperature=None,
    ):
        calls.append("block_gen")
        assert force_all is True
        return orch.StageReport("block_gen", "ok")

    monkeypatch.setattr(orch, "_load_chunks", fake_load_chunks)
    monkeypatch.setattr(orch, "_run_extractor", fake_extractor)
    monkeypatch.setattr(orch, "_run_mapper", fake_mapper)
    monkeypatch.setattr(orch, "_run_enricher", fake_enricher)
    monkeypatch.setattr(orch, "_run_block_gen", fake_block_gen)

    report = orch.run_course_pipeline("course-slug", force_all=True)

    assert calls == ["chunker", "extractor", "mapper", "enricher", "block_gen"]
    assert report.status == "ok"


def test_chunker_artifact_round_trips_by_fingerprint(tmp_path, monkeypatch):
    monkeypatch.setattr(orch, "ARTIFACT_ROOT", tmp_path)
    chunks = [{"file": "lecture.pdf", "chunk_index": 0, "text": "hello"}]

    path = orch._save_chunker_artifact("course-slug", "fingerprint-1", chunks)

    assert path == tmp_path / "chunker" / "course-slug" / "fingerprint-1.json"
    assert orch._load_chunker_artifact("course-slug", "fingerprint-1") == chunks
    assert orch._load_chunker_artifact("course-slug", "missing") is None


def test_course_pipeline_loads_chunker_artifact_when_chunker_skipped_but_extractor_runs(
    monkeypatch,
):
    calls: list[str] = []
    artifact_chunks = [{"chunk_index": 0, "text": "from artifact"}]

    monkeypatch.setattr(orch.db, "upsert_course", lambda *args, **kwargs: "course-id")
    monkeypatch.setattr(orch.db, "upsert_pipeline_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(orch, "_chunker_fingerprint", lambda *args, **kwargs: "chunker-fp")
    monkeypatch.setattr(orch, "_extractor_fingerprint", lambda *args, **kwargs: "extractor-fp")
    monkeypatch.setattr(orch, "_mapper_fingerprint", lambda *args, **kwargs: "mapper-fp")

    def fake_state_matches(course_id, stage, subject_key, fingerprint, **kwargs):
        return stage == "chunker"

    def fail_load_chunks(*args, **kwargs):
        raise AssertionError("chunker output should come from artifact")

    def fake_load_artifact(course_slug, fingerprint):
        calls.append("artifact")
        assert fingerprint == "chunker-fp"
        return artifact_chunks

    def fake_extractor(course_slug, chunks, *, dry_run):
        calls.append("extractor")
        assert chunks == artifact_chunks
        return orch.StageReport("extractor", "ok"), {"topic-a": "topic-id-a"}

    def fake_mapper(course_slug, *, dry_run):
        calls.append("mapper")
        return orch.StageReport("mapper", "ok")

    def fake_enricher(
        course_slug,
        *,
        include_thin,
        dry_run,
        force_all=False,
        course_id=None,
    ):
        calls.append("enricher")
        return orch.StageReport("enricher", "ok")

    def fake_block_gen(
        course_slug,
        *,
        dry_run,
        force_all=False,
        mapper_stage_status="ok",
        allow_degraded_mapper=False,
        model=None,
        max_tokens=None,
        temperature=None,
    ):
        calls.append("block_gen")
        return orch.StageReport("block_gen", "ok")

    monkeypatch.setattr(orch.db, "pipeline_state_matches", fake_state_matches)
    monkeypatch.setattr(orch, "_load_chunks", fail_load_chunks)
    monkeypatch.setattr(orch, "_load_chunker_artifact", fake_load_artifact)
    monkeypatch.setattr(orch, "_run_extractor", fake_extractor)
    monkeypatch.setattr(orch, "_run_mapper", fake_mapper)
    monkeypatch.setattr(orch, "_run_enricher", fake_enricher)
    monkeypatch.setattr(orch, "_run_block_gen", fake_block_gen)

    report = orch.run_course_pipeline("course-slug")

    assert calls == ["artifact", "extractor", "mapper", "enricher", "block_gen"]
    assert report.status == "ok"


def test_run_enricher_skips_when_fingerprint_matches(monkeypatch):
    monkeypatch.setattr(orch, "_enricher_fingerprint", lambda *args, **kwargs: "fp")
    monkeypatch.setattr(orch.db, "pipeline_state_matches", lambda *args, **kwargs: True)

    def fail_enrich(*args, **kwargs):
        raise AssertionError("enricher should be skipped")

    import pipeline.enricher as enricher

    monkeypatch.setattr(enricher, "enrich_course", fail_enrich)

    stage = orch._run_enricher(
        "course-slug",
        include_thin=False,
        dry_run=False,
        course_id="course-id",
    )

    assert stage.status == "skipped"
    assert stage.details["reason"] == "fingerprint_match"


def test_run_enricher_stores_post_enrichment_fingerprint(monkeypatch):
    fingerprints = iter(["pre-fp", "post-fp"])
    state_writes = []

    monkeypatch.setattr(
        orch,
        "_enricher_fingerprint",
        lambda *args, **kwargs: next(fingerprints),
    )
    monkeypatch.setattr(orch.db, "pipeline_state_matches", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        orch.db,
        "upsert_pipeline_state",
        lambda *args, **kwargs: state_writes.append(args),
    )

    result = EnrichmentResult(
        topic_id="topic-id",
        slug="topic-slug",
        status="ok",
        urls_fetched=1,
        chunks_written=2,
        before_top_similarity=0.1,
        after_top_similarity=0.8,
        coverage_before="sparse",
        coverage_after="dense",
    )

    import pipeline.enricher as enricher

    monkeypatch.setattr(enricher, "enrich_course", lambda *args, **kwargs: [result])

    stage = orch._run_enricher(
        "course-slug",
        include_thin=True,
        dry_run=False,
        course_id="course-id",
    )

    assert stage.status == "ok"
    assert stage.details["fingerprint"] == "post-fp"
    assert state_writes[0][:5] == (
        "course-id",
        "enricher",
        "course",
        "post-fp",
        "ok",
    )


def test_run_block_gen_blocks_when_mapper_stage_failed():
    stage = orch._run_block_gen(
        "course-slug",
        dry_run=True,
        mapper_stage_status="failed",
    )

    assert stage.status == "blocked"
    assert stage.details == {
        "reason": "mapper_stage_not_ok",
        "mapper_status": "failed",
    }


def test_run_block_gen_blocks_when_mapper_state_not_ready(monkeypatch):
    import pipeline.block_gen as bg

    monkeypatch.setattr(
        bg,
        "get_mapper_readiness",
        lambda course_slug: bg.MapperReadiness(
            False,
            "missing_pipeline_state",
            expected_fingerprint="mapper-fp",
        ),
    )

    stage = orch._run_block_gen(
        "course-slug",
        dry_run=True,
        mapper_stage_status="skipped",
    )

    assert stage.status == "blocked"
    assert stage.details["reason"] == "missing_pipeline_state"
    assert stage.details["expected_fingerprint"] == "mapper-fp"


def test_run_block_gen_override_allows_degraded_mapper(monkeypatch):
    import pipeline.block_gen as bg

    monkeypatch.setattr(
        bg,
        "get_mapper_readiness",
        lambda course_slug: bg.MapperReadiness(False, "status_not_ok", actual_status="failed"),
    )
    monkeypatch.setattr(bg, "_resolve_generation_targets", lambda *args, **kwargs: [])

    stage = orch._run_block_gen(
        "course-slug",
        dry_run=True,
        mapper_stage_status="failed",
        allow_degraded_mapper=True,
    )

    assert stage.status == "dry_run"
    assert stage.details["topics"] == 0


def test_course_pipeline_persists_failed_mapper_state(monkeypatch):
    state_writes = []

    monkeypatch.setattr(orch.db, "upsert_course", lambda *args, **kwargs: "course-id")
    monkeypatch.setattr(orch.db, "pipeline_state_matches", lambda *args, **kwargs: False)
    monkeypatch.setattr(
        orch.db,
        "upsert_pipeline_state",
        lambda *args, **kwargs: state_writes.append(args),
    )
    monkeypatch.setattr(orch, "_chunker_fingerprint", lambda *args, **kwargs: "chunker-fp")
    monkeypatch.setattr(orch, "_extractor_fingerprint", lambda *args, **kwargs: "extractor-fp")
    monkeypatch.setattr(orch, "_mapper_fingerprint", lambda *args, **kwargs: "mapper-fp")
    monkeypatch.setattr(
        orch,
        "_load_chunks",
        lambda *args, **kwargs: [{"chunk_index": 0}],
    )
    monkeypatch.setattr(
        orch,
        "_run_extractor",
        lambda *args, **kwargs: (orch.StageReport("extractor", "ok"), {}),
    )

    def raise_mapper(*args, **kwargs):
        raise RuntimeError("mapper blew up")

    monkeypatch.setattr(orch, "_run_mapper", raise_mapper)

    with pytest.raises(RuntimeError, match="mapper blew up"):
        orch.run_course_pipeline("course-slug")

    assert state_writes[-1] == (
        "course-id",
        "mapper",
        "course",
        "mapper-fp",
        "failed",
        {
            "error_type": "RuntimeError",
            "error": "mapper blew up",
        },
    )
