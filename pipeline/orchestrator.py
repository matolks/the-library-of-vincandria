"""
Agent 3 orchestrator: generate and persist teaching blocks for one topic.

Ties together get_topic_context, build_prompt, call_llm, both validators,
and replace_topic_blocks. Implements §6's sparse-coverage refusal and the
one-shot retry-on-validation-failure protocol.

Public entry point: generate_blocks_for_topic(topic_id) -> GenerationResult.
Returns structured outcomes; never raises on expected paths (sparse coverage,
validation failure, parse failure). Programmer errors and API/transport
failures propagate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from pipeline import db
from pipeline.anchor_integrity import validate_anchor_integrity
from pipeline.block_gen import get_topic_context
from pipeline.block_schema import validate_block_schema
from pipeline.llm import LLMResponseError, LLMResult, call_llm
from pipeline.prompt import PROMPT_VERSION, build_prompt


MAX_ATTEMPTS = 2  # one initial + one retry, per §6


@dataclass(frozen=True)
class GenerationResult:
    topic_id: str
    status: str  # "ok" | "refused_sparse" | "failed_validation" | "failed_parse"
    blocks_written: int
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    usd_cost: float
    model: str
    attempts: int
    top_similarity: float
    dry_run: bool = False
    validation_errors: tuple[str, ...] = ()
    reconciler_stats: dict | None = None


def generate_blocks_for_topic(
    topic_id: str, *, dry_run: bool = False
) -> GenerationResult:
    """Generate blocks for one topic. Persists unless dry_run=True."""
    context = get_topic_context(topic_id)

    if context.coverage == "sparse":
        return GenerationResult(
            topic_id=topic_id,
            status="refused_sparse",
            blocks_written=0,
            input_tokens=0, output_tokens=0,
            cache_creation_tokens=0, cache_read_tokens=0,
            usd_cost=0.0, model="", attempts=0,
            top_similarity=context.top_similarity,
            dry_run=dry_run,
        )

    system, user = build_prompt(context)
    pinned_cohorts = [c for c in context.cohorts if c.pinned]

    totals = _TokenAccumulator()
    current_user = user
    last_model = ""

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = call_llm(system, current_user)
        except LLMResponseError as e:
            if attempt == MAX_ATTEMPTS:
                return _failure(
                    topic_id, "failed_parse", totals, last_model, attempt,
                    context.top_similarity, dry_run, (str(e),),
                )
            current_user = _build_retry_prompt(
                user, [f"Response could not be parsed as JSON: {e}"], e.raw_text
            )
            continue

        totals.add(result)
        last_model = result.model

        allowed_chunk_ids = {chunk.id for chunk in context.chunks}
        errors = _validate(result.blocks, pinned_cohorts, allowed_chunk_ids)
        if not errors:
            pinned_ids, sequence = _to_reconciler_shape(result.blocks, result.model)
            stats = (
                None if dry_run
                else db.replace_topic_blocks(topic_id, pinned_ids, sequence)
            )
            return GenerationResult(
                topic_id=topic_id,
                status="ok",
                blocks_written=len(sequence),
                input_tokens=totals.input,
                output_tokens=totals.output,
                cache_creation_tokens=totals.cache_create,
                cache_read_tokens=totals.cache_read,
                usd_cost=totals.cost,
                model=last_model,
                attempts=attempt,
                top_similarity=context.top_similarity,
                dry_run=dry_run,
                reconciler_stats=stats,
            )

        if attempt == MAX_ATTEMPTS:
            return _failure(
                topic_id, "failed_validation", totals, last_model, attempt,
                context.top_similarity, dry_run, tuple(errors),
            )
        current_user = _build_retry_prompt(user, errors, result.raw_text)

    raise RuntimeError("unreachable: orchestrator exited the retry loop")


# ---- helpers --------------------------------------------------------------


class _TokenAccumulator:
    __slots__ = ("input", "output", "cache_create", "cache_read", "cost")

    def __init__(self) -> None:
        self.input = 0
        self.output = 0
        self.cache_create = 0
        self.cache_read = 0
        self.cost = 0.0

    def add(self, r: LLMResult) -> None:
        self.input += r.input_tokens
        self.output += r.output_tokens
        self.cache_create += r.cache_creation_tokens
        self.cache_read += r.cache_read_tokens
        self.cost += r.usd_cost


def _failure(
    topic_id: str, status: str, totals: _TokenAccumulator,
    model: str, attempts: int, top_sim: float, dry_run: bool,
    errors: tuple[str, ...],
) -> GenerationResult:
    return GenerationResult(
        topic_id=topic_id,
        status=status,
        blocks_written=0,
        input_tokens=totals.input,
        output_tokens=totals.output,
        cache_creation_tokens=totals.cache_create,
        cache_read_tokens=totals.cache_read,
        usd_cost=totals.cost,
        model=model,
        attempts=attempts,
        top_similarity=top_sim,
        dry_run=dry_run,
        validation_errors=errors,
    )


def _validate(
    blocks: list[dict],
    pinned_cohorts,
    allowed_chunk_ids: set[str] | None = None,
) -> list[str]:
    """Schema (per block) + anchor integrity (whole sequence). Flat error list."""
    errs: list[str] = []
    pinned_ids = {b.id for cohort in pinned_cohorts for b in cohort.blocks}
    allowed_chunk_ids = allowed_chunk_ids or set()
    for i, block in enumerate(blocks):
        if block.get("id") in pinned_ids:
            continue
        if block.get("type") == "image":
            errs.append(
                f"blocks[{i}]: Agent 3 must not emit image blocks; "
                "image is admin/editor-only"
            )
        for e in validate_block_schema(block):
            errs.append(f"blocks[{i}]: {e}")
        errs.extend(_validate_source_chunk_ids(block, allowed_chunk_ids, i))
    errs.extend(validate_anchor_integrity(blocks, pinned_cohorts))
    return errs


def _validate_source_chunk_ids(
    block: dict, allowed_chunk_ids: set[str], index: int
) -> list[str]:
    meta = block.get("generation_metadata")
    if not isinstance(meta, dict):
        return []
    ids = meta.get("source_chunk_ids")
    if not isinstance(ids, list):
        return []
    unknown = sorted({chunk_id for chunk_id in ids if chunk_id not in allowed_chunk_ids})
    if not unknown:
        return []
    return [
        f"blocks[{index}]: generation_metadata.source_chunk_ids contains "
        f"unknown chunk id(s) {unknown}; use only chunk IDs from SOURCE CHUNKS"
    ]


def _build_retry_prompt(original_user: str, errors: list[str], raw_text: str) -> str:
    bulleted = "\n".join(f"- {e}" for e in errors)
    truncated = raw_text[:8000]
    return f"""{original_user}

---

CORRECTION

Your previous response had the following problems:
{bulleted}

Here is what you previously returned (truncated to 8000 chars if longer):
{truncated}

Regenerate the full response, correcting every issue listed above. All
original requirements and the system prompt still apply. Output JSON only.
"""


def _to_reconciler_shape(
    blocks: list[dict], model: str
) -> tuple[list[str], list[dict]]:
    """Split model output into (pinned_ids, sequence) for replace_topic_blocks."""
    pinned_ids: list[str] = []
    sequence: list[dict] = []
    for block in blocks:
        if block.get("id") is not None:
            pinned_ids.append(block["id"])
            sequence.append({"id": block["id"]})
        else:
            seq_item: dict = {
                "type": block["type"],
                "content": _to_storage_content(block),
                "generation_metadata": _build_metadata(
                    block.get("generation_metadata"), model
                ),
            }
            if block.get("group_id") is not None:
                seq_item["group_id"] = block["group_id"]
            sequence.append(seq_item)
    return pinned_ids, sequence


def _build_metadata(from_model, model: str) -> dict:
    chunk_ids: list[str] = []
    if isinstance(from_model, dict):
        ids = from_model.get("source_chunk_ids")
        if isinstance(ids, list):
            chunk_ids = [i for i in ids if isinstance(i, str)]
    return {
        "agent": "agent3",
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "source_chunk_ids": chunk_ids,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def _to_storage_content(block: dict) -> dict:
    """Convert model block shape into the BlockNote-shaped JSON we persist."""
    stored = {
        "type": block["type"],
        "content": block["content"],
    }
    if "props" in block:
        stored["props"] = block["props"]
    return stored
