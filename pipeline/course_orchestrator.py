"""
Course-level pipeline orchestrator.

Runs extractor -> mapper -> enricher -> block_gen and aggregates status,
token, and cost reporting across stages.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field

from pipeline import db


@dataclass
class StageReport:
    stage: str
    status: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    usd_cost: float = 0.0
    details: dict = field(default_factory=dict)


@dataclass
class CoursePipelineReport:
    course_slug: str
    status: str
    stages: list[StageReport]
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    usd_cost: float


def run_course_pipeline(
    course_slug: str,
    *,
    dry_run: bool = False,
    include_thin: bool = False,
    skip_chunker: bool = False,
    chunk_file: str | None = None,
) -> CoursePipelineReport:
    stages: list[StageReport] = []

    chunks = _load_chunks(course_slug, skip_chunker=skip_chunker, chunk_file=chunk_file)

    extraction_stage, topic_id_map = _run_extractor(course_slug, chunks, dry_run=dry_run)
    stages.append(extraction_stage)

    mapper_stage = _run_mapper(course_slug, dry_run=dry_run)
    stages.append(mapper_stage)

    enricher_stage = _run_enricher(
        course_slug, include_thin=include_thin, dry_run=dry_run
    )
    stages.append(enricher_stage)

    block_stage = _run_block_gen(course_slug, dry_run=dry_run)
    stages.append(block_stage)

    status = "ok" if all(s.status in {"ok", "dry_run"} for s in stages) else "partial"
    return _aggregate(course_slug, status, stages)


def _load_chunks(
    course_slug: str, *, skip_chunker: bool, chunk_file: str | None
) -> list[dict]:
    if chunk_file:
        with open(chunk_file) as f:
            return json.load(f)
    if skip_chunker:
        return []

    from pipeline.chunker import chunk_course

    return chunk_course(course_slug)


def _run_extractor(
    course_slug: str, chunks: list[dict], *, dry_run: bool
) -> tuple[StageReport, dict[str, str]]:
    from pipeline import extractor

    existing = db.get_existing_topics_for_course(course_slug)
    llm_result = extractor.extract_topics_with_usage(
        course_slug, chunks, existing=existing
    )
    extraction = llm_result.extraction
    topic_count = len(extraction.get("topics", []))
    if dry_run:
        return (
            StageReport(
                "extractor",
                "dry_run",
                input_tokens=llm_result.input_tokens,
                output_tokens=llm_result.output_tokens,
                usd_cost=llm_result.usd_cost,
                details={"topics": topic_count, "chunks": len(chunks)},
            ),
            {},
        )

    topic_id_map = extractor.write_topics(course_slug, extraction, chunks)
    return (
        StageReport(
            "extractor",
            "ok",
            input_tokens=llm_result.input_tokens,
            output_tokens=llm_result.output_tokens,
            usd_cost=llm_result.usd_cost,
            details={"topics": len(topic_id_map), "chunks": len(chunks)},
        ),
        topic_id_map,
    )


def _run_mapper(course_slug: str, *, dry_run: bool) -> StageReport:
    from pipeline import mapper

    course_id, topics = mapper.get_course_topics(course_slug)
    edges, tok_in, tok_out = mapper.extract_dependencies(course_slug, course_id, topics)
    cycle = mapper.detect_cycle(edges)
    cost = (tok_in * mapper.PRICE_IN + tok_out * mapper.PRICE_OUT) / 1_000_000
    details = {"topics": len(topics), "edges": len(edges)}
    if cycle:
        details["cycle"] = cycle
        return StageReport(
            "mapper", "cycle_detected", tok_in, tok_out, usd_cost=cost, details=details
        )
    if not dry_run:
        mapper.write_dependencies(edges, {t["id"] for t in topics})
    return StageReport(
        "mapper",
        "dry_run" if dry_run else "ok",
        input_tokens=tok_in,
        output_tokens=tok_out,
        usd_cost=cost,
        details=details,
    )


def _run_enricher(course_slug: str, *, include_thin: bool, dry_run: bool) -> StageReport:
    from pipeline.enricher import enrich_course

    results = enrich_course(course_slug, include_thin=include_thin, dry_run=dry_run)
    status_counts: dict[str, int] = {}
    chunks_written = 0
    for result in results:
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
        chunks_written += result.chunks_written
    hard_failures = sum(
        count
        for status, count in status_counts.items()
        if status not in {"ok", "dry_run", "no_sources"}
    )
    status = "ok" if hard_failures == 0 else "partial"
    if dry_run and hard_failures == 0:
        status = "dry_run"
    return StageReport(
        "enricher",
        status,
        details={
            "topics": len(results),
            "chunks_written": chunks_written if not dry_run else 0,
            "candidate_chunks": chunks_written if dry_run else None,
            "statuses": status_counts,
            "results": [asdict(r) for r in results],
        },
    )


def _run_block_gen(course_slug: str, *, dry_run: bool) -> StageReport:
    from pipeline.block_gen import _resolve_generation_targets
    from pipeline.orchestrator import generate_blocks_for_topic

    targets = _resolve_generation_targets(course_slug, None)
    status_counts: dict[str, int] = {}
    blocks_written = 0
    tok_in = tok_out = cache_create = cache_read = 0
    cost = 0.0
    results = []
    for topic_id, slug in targets:
        result = generate_blocks_for_topic(topic_id, dry_run=dry_run)
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
        blocks_written += result.blocks_written
        tok_in += result.input_tokens
        tok_out += result.output_tokens
        cache_create += result.cache_creation_tokens
        cache_read += result.cache_read_tokens
        cost += result.usd_cost
        row = asdict(result)
        row["slug"] = slug
        results.append(row)

    failures = sum(count for status, count in status_counts.items() if status != "ok")
    status = "ok" if failures == 0 else "partial"
    if dry_run and failures == 0:
        status = "dry_run"
    return StageReport(
        "block_gen",
        status,
        input_tokens=tok_in,
        output_tokens=tok_out,
        cache_creation_tokens=cache_create,
        cache_read_tokens=cache_read,
        usd_cost=cost,
        details={
            "topics": len(targets),
            "blocks_written": blocks_written,
            "statuses": status_counts,
            "results": results,
        },
    )


def _aggregate(
    course_slug: str, status: str, stages: list[StageReport]
) -> CoursePipelineReport:
    return CoursePipelineReport(
        course_slug=course_slug,
        status=status,
        stages=stages,
        input_tokens=sum(s.input_tokens for s in stages),
        output_tokens=sum(s.output_tokens for s in stages),
        cache_creation_tokens=sum(s.cache_creation_tokens for s in stages),
        cache_read_tokens=sum(s.cache_read_tokens for s in stages),
        usd_cost=sum(s.usd_cost for s in stages),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the full course pipeline.")
    parser.add_argument("--course", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-thin", action="store_true")
    parser.add_argument("--skip-chunker", action="store_true")
    parser.add_argument("--chunks", help="precomputed chunk JSON file")
    args = parser.parse_args()

    try:
        report = run_course_pipeline(
            args.course,
            dry_run=args.dry_run,
            include_thin=args.include_thin,
            skip_chunker=args.skip_chunker,
            chunk_file=args.chunks,
        )
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
        if report.status not in {"ok", "dry_run"}:
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
