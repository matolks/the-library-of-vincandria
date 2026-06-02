from __future__ import annotations

import pytest

from pipeline.rerun_canary import (
    CanaryError,
    validate_full_vs_incremental_reports,
    validate_noop_rerun_report,
)


def test_validate_noop_rerun_report_accepts_all_skipped_block_topics():
    validate_noop_rerun_report(_report(block_statuses={"skipped": 2}))


def test_validate_noop_rerun_report_rejects_block_writes():
    report = _report(block_statuses={"skipped": 1, "ok": 1}, blocks_written=3)

    with pytest.raises(CanaryError, match="wrote 3 blocks"):
        validate_noop_rerun_report(report)


def test_validate_noop_rerun_report_can_require_enricher_skip():
    report = _report(block_statuses={"skipped": 2}, enricher_status="ok")

    with pytest.raises(CanaryError, match="enricher did not skip"):
        validate_noop_rerun_report(report, require_enricher_skipped=True)


def test_validate_full_vs_incremental_reports_accepts_matching_config():
    validate_full_vs_incremental_reports(
        _report(block_statuses={"ok": 2}, blocks_written=8),
        _report(block_statuses={"skipped": 1, "ok": 1}, blocks_written=4),
    )


def test_validate_full_vs_incremental_reports_rejects_model_drift():
    full = _report(block_statuses={"ok": 2}, model="claude-sonnet-4-6")
    incremental = _report(block_statuses={"ok": 2}, model="claude-opus-4-7")

    with pytest.raises(CanaryError, match="generation_config mismatch"):
        validate_full_vs_incremental_reports(full, incremental)


def _report(
    *,
    block_statuses: dict[str, int],
    blocks_written: int = 0,
    model: str = "claude-sonnet-4-6",
    enricher_status: str = "ok",
) -> dict:
    topics = sum(block_statuses.values())
    return {
        "course_slug": "fixture-course",
        "status": "ok",
        "stages": [
            _stage("chunker", "skipped"),
            _stage("extractor", "skipped"),
            _stage("mapper", "skipped"),
            _stage("enricher", enricher_status),
            {
                "stage": "block_gen",
                "status": "ok",
                "details": {
                    "topics": topics,
                    "blocks_written": blocks_written,
                    "statuses": block_statuses,
                    "generation_config": {
                        "model": model,
                        "decoding": {"max_tokens": 20000, "temperature": 0},
                        "output_format_version": "agent3.block-output.v1",
                    },
                },
            },
        ],
    }


def _stage(stage: str, status: str) -> dict:
    details = {"reason": "fingerprint_match"} if status == "skipped" else {}
    return {"stage": stage, "status": status, "details": details}
