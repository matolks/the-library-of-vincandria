"""
Validation helpers for change-aware rerun rollouts.

These checks operate on the JSON report emitted by pipeline.course_orchestrator.
They deliberately do not talk to the database; the intended workflow is:

1. Run a full fixture course in scratch/dev and save the report.
2. Run a no-op rerun and save the report.
3. Use this module to assert the report-level invariants before trusting skips.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class CanaryError(AssertionError):
    """Raised when a rerun canary invariant fails."""


def validate_noop_rerun_report(
    report: dict[str, Any],
    *,
    expected_skipped_stages: tuple[str, ...] = ("chunker", "extractor", "mapper"),
    require_enricher_skipped: bool = False,
) -> None:
    """Assert a no-op rerun did not write blocks and skipped known stages."""
    if report.get("status") not in {"ok", "dry_run"}:
        raise CanaryError(f"report status is {report.get('status')!r}")

    stages = _stage_map(report)
    for stage_name in expected_skipped_stages:
        stage = _require_stage(stages, stage_name)
        if stage.get("status") != "skipped":
            raise CanaryError(
                f"{stage_name} status is {stage.get('status')!r}, expected 'skipped'"
            )
        reason = stage.get("details", {}).get("reason")
        if reason != "fingerprint_match":
            raise CanaryError(
                f"{stage_name} skip reason is {reason!r}, expected 'fingerprint_match'"
            )

    if require_enricher_skipped:
        enricher = _require_stage(stages, "enricher")
        if enricher.get("status") != "skipped":
            raise CanaryError(
                "enricher did not skip; enricher fingerprints are not ready "
                "for an all-stages no-op assertion"
            )

    block_gen = _require_stage(stages, "block_gen")
    details = block_gen.get("details") or {}
    if details.get("blocks_written") != 0:
        raise CanaryError(
            f"block_gen wrote {details.get('blocks_written')!r} blocks, expected 0"
        )
    statuses = details.get("statuses") or {}
    disallowed = {
        status: count
        for status, count in statuses.items()
        if status != "skipped" and count
    }
    if disallowed:
        raise CanaryError(f"block_gen had non-skip statuses on no-op rerun: {disallowed}")
    if details.get("topics") != statuses.get("skipped"):
        raise CanaryError(
            "block_gen skipped count does not match topic count: "
            f"topics={details.get('topics')!r} skipped={statuses.get('skipped')!r}"
        )


def validate_full_vs_incremental_reports(
    full_report: dict[str, Any],
    incremental_report: dict[str, Any],
) -> None:
    """Assert two saved reports are comparable as a full/incremental canary."""
    if full_report.get("course_slug") != incremental_report.get("course_slug"):
        raise CanaryError(
            "course_slug mismatch: "
            f"full={full_report.get('course_slug')!r} "
            f"incremental={incremental_report.get('course_slug')!r}"
        )
    for label, report in (("full", full_report), ("incremental", incremental_report)):
        if report.get("status") not in {"ok", "dry_run"}:
            raise CanaryError(f"{label} report status is {report.get('status')!r}")

    full_block = _require_stage(_stage_map(full_report), "block_gen")
    incr_block = _require_stage(_stage_map(incremental_report), "block_gen")
    full_config = (full_block.get("details") or {}).get("generation_config")
    incr_config = (incr_block.get("details") or {}).get("generation_config")
    if full_config != incr_config:
        raise CanaryError(
            "Agent 3 generation_config mismatch between full and incremental reports"
        )

    incr_details = incr_block.get("details") or {}
    if incr_details.get("blocks_written", 0) < 0:
        raise CanaryError("incremental block_gen blocks_written cannot be negative")
    statuses = incr_details.get("statuses") or {}
    failures = {
        status: count
        for status, count in statuses.items()
        if status not in {"ok", "skipped"} and count
    }
    if failures:
        raise CanaryError(f"incremental block_gen had failure statuses: {failures}")


def _stage_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    stages = report.get("stages")
    if not isinstance(stages, list):
        raise CanaryError("report.stages must be a list")
    out = {}
    for stage in stages:
        if isinstance(stage, dict) and isinstance(stage.get("stage"), str):
            out[stage["stage"]] = stage
    return out


def _require_stage(
    stages: dict[str, dict[str, Any]],
    stage_name: str,
) -> dict[str, Any]:
    try:
        return stages[stage_name]
    except KeyError as exc:
        raise CanaryError(f"missing stage {stage_name!r}") from exc


def _load_json(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict):
        raise CanaryError(f"{path} must contain a JSON object")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate change-aware rerun reports.")
    sub = parser.add_subparsers(dest="command", required=True)

    noop = sub.add_parser("noop", help="validate a no-op rerun report")
    noop.add_argument("--report", required=True)
    noop.add_argument("--require-enricher-skipped", action="store_true")

    compare = sub.add_parser("compare", help="compare full and incremental reports")
    compare.add_argument("--full-report", required=True)
    compare.add_argument("--incremental-report", required=True)

    args = parser.parse_args()
    if args.command == "noop":
        validate_noop_rerun_report(
            _load_json(args.report),
            require_enricher_skipped=args.require_enricher_skipped,
        )
    elif args.command == "compare":
        validate_full_vs_incremental_reports(
            _load_json(args.full_report),
            _load_json(args.incremental_report),
        )
    print("canary ok")


if __name__ == "__main__":
    main()
