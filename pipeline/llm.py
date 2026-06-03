"""
LLM wrapper for Agent 3 block generation.

Thin transport: takes (system, user), calls Anthropic API, returns parsed
JSON blocks plus token accounting. No retry logic — that lives in the
orchestrator so it can append validator errors to the next attempt.

System prompt is sent with cache_control=ephemeral. Repeated calls within
the 5-minute window hit the prompt cache and pay ~10% of input rate for
the cached portion.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

import anthropic


# Override via env or call kwarg. Align with the mapper if it pins a model.
DEFAULT_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
DEFAULT_MAX_TOKENS = 20000
DEFAULT_TEMPERATURE = 0
DEFAULT_STRUCTURED_JSON = os.environ.get("CLAUDE_AGENT3_STRUCTURED_JSON", "0") == "1"
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("CLAUDE_AGENT3_TIMEOUT", "180"))

# USD per million tokens. Verified May 2026. Update when Anthropic does.
# Cache write = 1.25x input; cache read = 0.10x input.
PRICING_USD_PER_MTOK: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00, "cache_write": 3.75, "cache_read": 0.30},
    "claude-opus-4-7":   {"input": 5.00, "output": 25.00, "cache_write": 6.25, "cache_read": 0.50},
    "claude-opus-4-6":   {"input": 5.00, "output": 25.00, "cache_write": 6.25, "cache_read": 0.50},
    "claude-haiku-4-5":  {"input": 1.00, "output":  5.00, "cache_write": 1.25, "cache_read": 0.10},
}


BLOCKS_JSON_SCHEMA = {
    "type": "object",
    "required": ["blocks"],
    "properties": {
        "blocks": {
            "type": "array",
            "items": {"type": "object"},
        },
    },
}


@dataclass(frozen=True)
class LLMResult:
    blocks: list[dict]
    raw_text: str
    model: str
    input_tokens: int           # uncached input
    output_tokens: int
    cache_creation_tokens: int  # input tokens written to cache (first call of window)
    cache_read_tokens: int      # input tokens read from cache (subsequent calls)
    usd_cost: float


class LLMResponseError(Exception):
    """Response wasn't valid JSON or lacked a `blocks` array.

    Carries the raw text so the orchestrator can append it to a retry prompt.
    """
    def __init__(self, message: str, raw_text: str):
        super().__init__(message)
        self.raw_text = raw_text


def call_llm(
    system: str,
    user: str,
    *,
    model: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = DEFAULT_TEMPERATURE,
    structured_json: bool = DEFAULT_STRUCTURED_JSON,
    client: anthropic.Anthropic | None = None,
) -> LLMResult:
    """Call the model and return parsed blocks plus token accounting.

    Does not retry. The orchestrator handles retry-with-correction when
    validators reject the result.

    Raises:
        LLMResponseError: response wasn't valid JSON or lacked `blocks`.
        anthropic.APIError: any transport/API failure; propagates unchanged.
    """
    model = model or DEFAULT_MODEL
    client = client or anthropic.Anthropic(timeout=REQUEST_TIMEOUT_SECONDS)

    request = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": user}],
    }
    if structured_json:
        request["tools"] = [
            {
                "name": "emit_blocks",
                "description": "Return the generated teaching block JSON object.",
                "input_schema": BLOCKS_JSON_SCHEMA,
            }
        ]
        request["tool_choice"] = {"type": "tool", "name": "emit_blocks"}

    response = client.messages.create(**request)

    raw_text, blocks = (
        _extract_tool_payload(response)
        if structured_json
        else _extract_text_payload(response)
    )

    usage = response.usage
    input_tokens = usage.input_tokens
    output_tokens = usage.output_tokens
    cache_creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0

    return LLMResult(
        blocks=blocks,
        raw_text=raw_text,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation,
        cache_read_tokens=cache_read,
        usd_cost=_compute_cost(model, input_tokens, output_tokens, cache_creation, cache_read),
    )


# ---- helpers --------------------------------------------------------------


def _extract_text(response) -> str:
    return "".join(
        b.text for b in response.content if getattr(b, "type", None) == "text"
    ).strip()


def _extract_text_payload(response) -> tuple[str, list[dict]]:
    raw_text = _extract_text(response)
    return raw_text, _parse_blocks(raw_text)


def _extract_tool_payload(response) -> tuple[str, list[dict]]:
    for block in response.content:
        if getattr(block, "type", None) != "tool_use":
            continue
        if getattr(block, "name", None) != "emit_blocks":
            continue
        payload = getattr(block, "input", None)
        raw_text = json.dumps(payload, sort_keys=True)
        return raw_text, _coerce_blocks_payload(payload, raw_text)
    raw_text = _extract_text(response)
    raise LLMResponseError(
        "structured response did not include required emit_blocks tool call",
        raw_text,
    )


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _parse_blocks(raw_text: str) -> list[dict]:
    """Parse the model's response into a list of block dicts.

    Strips markdown fences defensively even though the prompt forbids them.
    Parse failures become LLMResponseError so the orchestrator can append
    the raw text to a retry message.
    """
    text = _FENCE_RE.sub("", raw_text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMResponseError(
            f"response was not valid JSON: {e.msg} at line {e.lineno} col {e.colno}",
            raw_text,
        )
    return _coerce_blocks_payload(parsed, raw_text)


def _coerce_blocks_payload(parsed, raw_text: str) -> list[dict]:
    if not isinstance(parsed, dict):
        raise LLMResponseError(
            f"response root must be a JSON object, got {type(parsed).__name__}",
            raw_text,
        )
    blocks = parsed.get("blocks")
    if not isinstance(blocks, list):
        raise LLMResponseError(
            "response object is missing the required `blocks` array",
            raw_text,
        )
    return blocks


def _compute_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int,
    cache_read_tokens: int,
) -> float:
    rates = PRICING_USD_PER_MTOK.get(model)
    if rates is None:
        return 0.0  # unknown model; cost report will read $0 — log a warning upstream if needed
    return (
        input_tokens * rates["input"]
        + output_tokens * rates["output"]
        + cache_creation_tokens * rates["cache_write"]
        + cache_read_tokens * rates["cache_read"]
    ) / 1_000_000
