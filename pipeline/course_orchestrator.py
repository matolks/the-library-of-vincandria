"""
Course-level pipeline orchestrator.

Runs extractor -> mapper -> enricher -> block_gen and aggregates status,
token, and cost reporting across stages.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from pipeline import db
from pipeline.fingerprints import fingerprint_payload


ARTIFACT_ROOT = Path(
    Path.cwd() / "scratch" / "pipeline_artifacts"
)


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
    force_all: bool = False,
    agent3_model: str | None = None,
    agent3_max_tokens: int | None = None,
    agent3_temperature: float | None = None,
) -> CoursePipelineReport:
    stages: list[StageReport] = []
    course_id = (
        db.get_course_id(course_slug)
        if dry_run
        else db.upsert_course(course_slug, course_slug.replace("-", " ").title())
    )

    chunker_fingerprint = _chunker_fingerprint(
        course_slug,
        skip_chunker=skip_chunker,
        chunk_file=chunk_file,
    )
    chunker_skipped = not force_all and bool(course_id) and db.pipeline_state_matches(
        course_id, "chunker", "course", chunker_fingerprint
    )
    chunks: list[dict] = []
    if chunker_skipped:
        artifact_path = _chunker_artifact_path(course_slug, chunker_fingerprint)
        stages.append(
            StageReport(
                "chunker",
                "skipped",
                details={
                    "fingerprint": chunker_fingerprint,
                    "reason": "fingerprint_match",
                    "artifact_path": str(artifact_path),
                },
            )
        )
    else:
        chunks = _load_chunks(course_slug, skip_chunker=skip_chunker, chunk_file=chunk_file)
        artifact_path = _chunker_artifact_path(course_slug, chunker_fingerprint)
        if not dry_run:
            artifact_path = _save_chunker_artifact(
                course_slug,
                chunker_fingerprint,
                chunks,
            )
        if course_id and not dry_run:
            db.upsert_pipeline_state(
                course_id,
                "chunker",
                "course",
                chunker_fingerprint,
                "ok",
                {
                    "chunks": len(chunks),
                    "skip_chunker": skip_chunker,
                    "artifact_path": str(artifact_path),
                },
            )
        stages.append(
            StageReport(
                "chunker",
                "ok",
                details={
                    "chunks": len(chunks),
                    "fingerprint": chunker_fingerprint,
                    "artifact_path": str(artifact_path),
                },
            )
        )

    extractor_fingerprint = _extractor_fingerprint(course_slug, chunker_fingerprint)
    if not force_all and course_id and db.pipeline_state_matches(
        course_id, "extractor", "course", extractor_fingerprint
    ):
        extraction_stage, topic_id_map = (
            StageReport(
                "extractor",
                "skipped",
                details={
                    "fingerprint": extractor_fingerprint,
                    "reason": "fingerprint_match",
                },
            ),
            {},
        )
    else:
        if chunker_skipped:
            chunks = _load_chunker_artifact(course_slug, chunker_fingerprint)
            if chunks is None:
                chunks = _load_chunks(
                    course_slug,
                    skip_chunker=skip_chunker,
                    chunk_file=chunk_file,
                )
        extraction_stage, topic_id_map = _run_extractor(
            course_slug, chunks, dry_run=dry_run
        )
        if extraction_stage.status in {"ok", "dry_run"} and not dry_run:
            db.upsert_pipeline_state(
                course_id,
                "extractor",
                "course",
                extractor_fingerprint,
                extraction_stage.status,
                extraction_stage.details,
            )
    stages.append(extraction_stage)

    mapper_fingerprint = _mapper_fingerprint(course_slug)
    if not force_all and course_id and db.pipeline_state_matches(
        course_id, "mapper", "course", mapper_fingerprint
    ):
        mapper_stage = StageReport(
            "mapper",
            "skipped",
            details={
                "fingerprint": mapper_fingerprint,
                "reason": "fingerprint_match",
            },
        )
    else:
        mapper_stage = _run_mapper(course_slug, dry_run=dry_run)
        if mapper_stage.status in {"ok", "dry_run"} and not dry_run:
            db.upsert_pipeline_state(
                course_id,
                "mapper",
                "course",
                mapper_fingerprint,
                mapper_stage.status,
                mapper_stage.details,
            )
    stages.append(mapper_stage)

    enricher_stage = _run_enricher(
        course_slug,
        include_thin=include_thin,
        dry_run=dry_run,
        force_all=force_all,
        course_id=course_id,
    )
    stages.append(enricher_stage)

    block_stage = _run_block_gen(
        course_slug,
        dry_run=dry_run,
        force_all=force_all,
        model=agent3_model,
        max_tokens=agent3_max_tokens,
        temperature=agent3_temperature,
    )
    stages.append(block_stage)

    ok_statuses = {"ok", "dry_run", "skipped"}
    status = "ok" if all(s.status in ok_statuses for s in stages) else "partial"
    return _aggregate(course_slug, status, stages)


def _chunker_fingerprint(
    course_slug: str,
    *,
    skip_chunker: bool,
    chunk_file: str | None,
) -> str:
    from pipeline import chunker
    from pipeline.parsers import is_supported

    if chunk_file:
        path = Path(chunk_file)
        stat = path.stat()
        subject = {
            "mode": "chunk_file",
            "path": str(path),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            "sha256": _file_sha256(path),
        }
    elif skip_chunker:
        subject = {"mode": "skip_chunker"}
    else:
        course_dir = Path(chunker.AISTACK_DOCS) / course_slug
        files = []
        if course_dir.exists():
            for path in sorted(p for p in course_dir.rglob("*") if p.is_file()):
                if not is_supported(str(path)):
                    continue
                stat = path.stat()
                files.append(
                    {
                        "path": str(path.relative_to(course_dir)),
                        "size": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns,
                    }
                )
        subject = {"mode": "course_dir", "root": str(course_dir), "files": files}
    return fingerprint_payload(
        {
            "stage": "chunker.v1",
            "chunk_size": chunker.CHUNK_SIZE,
            "chunk_overlap": chunker.CHUNK_OVERLAP,
            "ollama_summarize": chunker.OLLAMA_SUMMARIZE,
            "ollama_model": chunker.OLLAMA_MODEL,
            "subject": subject,
        }
    )


def _extractor_fingerprint(course_slug: str, chunker_fingerprint: str) -> str:
    from pipeline import extractor

    return fingerprint_payload(
        {
            "stage": "extractor.v1",
            "model": extractor.MODEL,
            "max_tokens": extractor.MAX_TOKENS,
            "system_prompt": extractor.SYSTEM_PROMPT,
            "topic_groups": extractor.TOPIC_GROUPS,
            "disallowed_new_group_slugs": sorted(extractor.DISALLOWED_NEW_GROUP_SLUGS),
            "chunker_fingerprint": chunker_fingerprint,
            "existing_topics": db.get_existing_topics_for_course(course_slug),
        }
    )


def _mapper_fingerprint(course_slug: str) -> str:
    from pipeline import mapper

    _course_id, topics = mapper.get_course_topics(course_slug)
    return fingerprint_payload(
        {
            "stage": "mapper.v1",
            "model": mapper.MODEL,
            "k_candidates": mapper.K_CANDIDATES,
            "system_prompt": mapper.SYSTEM_PROMPT,
            "manual_excluded_edges": sorted(mapper.MANUAL_EXCLUDED_EDGES),
            "topics": [
                {
                    "slug": t["slug"],
                    "title": t["title"],
                    "summary": t.get("summary"),
                }
                for t in topics
            ],
        }
    )


def _enricher_fingerprint(
    course_slug: str,
    *,
    include_thin: bool,
    max_fetches_per_topic: int | None = None,
) -> str:
    from pipeline import enricher

    max_fetches = (
        enricher.DEFAULT_MAX_FETCHES_PER_TOPIC
        if max_fetches_per_topic is None
        else max_fetches_per_topic
    )
    targets = enricher._select_targets(course_slug, None, include_thin)
    return fingerprint_payload(
        {
            "stage": "enricher.v1",
            "include_thin": include_thin,
            "max_fetches_per_topic": max_fetches,
            "weak_floor": enricher.WEAK_FLOOR,
            "strong_floor": enricher.STRONG_FLOOR,
            "thin_strong_chunks": enricher.THIN_STRONG_CHUNKS,
            "allowed_exact_hosts": sorted(enricher.ALLOWED_EXACT_HOSTS),
            "allowed_suffixes": sorted(enricher.ALLOWED_SUFFIXES),
            "curated_urls": {
                slug: list(urls)
                for slug, urls in sorted(enricher.CURATED_URLS.items())
            },
            "targets": [
                {
                    "slug": target.slug,
                    "status": target.status,
                    "top_similarity": round(target.top_similarity, 6),
                    "strong_chunks": target.strong_chunks,
                }
                for target in targets
            ],
        }
    )


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _chunker_artifact_path(course_slug: str, fingerprint: str) -> Path:
    return ARTIFACT_ROOT / "chunker" / course_slug / f"{fingerprint}.json"


def _save_chunker_artifact(
    course_slug: str,
    fingerprint: str,
    chunks: list[dict],
) -> Path:
    path = _chunker_artifact_path(course_slug, fingerprint)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "course_slug": course_slug,
        "fingerprint": fingerprint,
        "chunks": chunks,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return path


def _load_chunker_artifact(
    course_slug: str,
    fingerprint: str,
) -> list[dict] | None:
    path = _chunker_artifact_path(course_slug, fingerprint)
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    if (
        not isinstance(payload, dict)
        or payload.get("course_slug") != course_slug
        or payload.get("fingerprint") != fingerprint
        or not isinstance(payload.get("chunks"), list)
    ):
        raise ValueError(f"Invalid chunker artifact: {path}")
    return payload["chunks"]


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


def _run_enricher(
    course_slug: str,
    *,
    include_thin: bool,
    dry_run: bool,
    force_all: bool = False,
    course_id: str | None = None,
) -> StageReport:
    from pipeline.enricher import enrich_course

    fingerprint = _enricher_fingerprint(course_slug, include_thin=include_thin)
    if (
        not force_all
        and course_id
        and db.pipeline_state_matches(course_id, "enricher", "course", fingerprint)
    ):
        return StageReport(
            "enricher",
            "skipped",
            details={
                "fingerprint": fingerprint,
                "reason": "fingerprint_match",
            },
        )

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
    post_fingerprint = fingerprint
    if status == "ok":
        post_fingerprint = _enricher_fingerprint(
            course_slug,
            include_thin=include_thin,
        )
        if course_id and not dry_run:
            db.upsert_pipeline_state(
                course_id,
                "enricher",
                "course",
                post_fingerprint,
                "ok",
                {
                    "topics": len(results),
                    "chunks_written": chunks_written,
                    "statuses": status_counts,
                },
            )
    return StageReport(
        "enricher",
        status,
        details={
            "fingerprint": post_fingerprint,
            "topics": len(results),
            "chunks_written": chunks_written if not dry_run else 0,
            "candidate_chunks": chunks_written if dry_run else None,
            "statuses": status_counts,
            "results": [asdict(r) for r in results],
        },
    )


def _run_block_gen(
    course_slug: str,
    *,
    dry_run: bool,
    force_all: bool = False,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> StageReport:
    from pipeline import llm
    from pipeline.block_gen import (
        _resolve_generation_targets,
        agent3_generation_config,
        explain_topic_staleness,
    )
    from pipeline.orchestrator import generate_blocks_for_topic

    targets = _resolve_generation_targets(course_slug, None)
    resolved_max_tokens = (
        llm.DEFAULT_MAX_TOKENS if max_tokens is None else max_tokens
    )
    resolved_temperature = (
        llm.DEFAULT_TEMPERATURE if temperature is None else temperature
    )
    generation_config = agent3_generation_config(
        model=model,
        max_tokens=resolved_max_tokens,
        temperature=resolved_temperature,
    )
    status_counts: dict[str, int] = {}
    blocks_written = 0
    tok_in = tok_out = cache_create = cache_read = 0
    cost = 0.0
    results = []
    for topic_id, slug in targets:
        stale = explain_topic_staleness(
            topic_id,
            generation_config=generation_config,
        )
        if not force_all and not stale.stale:
            status_counts["skipped"] = status_counts.get("skipped", 0) + 1
            results.append({
                "topic_id": topic_id,
                "slug": slug,
                "status": "skipped",
                "reason": stale.reason,
                "context_fingerprint": stale.expected_fingerprint,
                "stored_fingerprints": stale.stored_fingerprints,
            })
            continue
        result = generate_blocks_for_topic(
            topic_id,
            dry_run=dry_run,
            model=model,
            max_tokens=resolved_max_tokens,
            temperature=resolved_temperature,
        )
        status_counts[result.status] = status_counts.get(result.status, 0) + 1
        blocks_written += result.blocks_written
        tok_in += result.input_tokens
        tok_out += result.output_tokens
        cache_create += result.cache_creation_tokens
        cache_read += result.cache_read_tokens
        cost += result.usd_cost
        row = asdict(result)
        row["slug"] = slug
        row["reason"] = "force_all" if force_all else stale.reason
        row["context_fingerprint"] = stale.expected_fingerprint
        results.append(row)

    failures = sum(
        count
        for status, count in status_counts.items()
        if status not in {"ok", "skipped"}
    )
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
            "force_all": force_all,
            "generation_config": generation_config,
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
    parser.add_argument("--force-all", action="store_true",
                        help="ignore stored fingerprints and regenerate all stages/topics")
    parser.add_argument("--agent3-model",
                        help="Agent 3 model override; included in block fingerprints")
    parser.add_argument("--agent3-max-tokens", type=int,
                        help="Agent 3 max_tokens override")
    parser.add_argument("--agent3-temperature", type=float,
                        help="Agent 3 temperature override")
    args = parser.parse_args()

    try:
        report = run_course_pipeline(
            args.course,
            dry_run=args.dry_run,
            include_thin=args.include_thin,
            skip_chunker=args.skip_chunker,
            chunk_file=args.chunks,
            force_all=args.force_all,
            agent3_model=args.agent3_model,
            agent3_max_tokens=args.agent3_max_tokens,
            agent3_temperature=args.agent3_temperature,
        )
        print(json.dumps(asdict(report), indent=2, sort_keys=True))
        if report.status not in {"ok", "dry_run"}:
            sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
