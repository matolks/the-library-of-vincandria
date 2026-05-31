"""
Prompt construction for Agent 3 (block generation).

Pure function: TopicContext -> (system, user). No I/O.

System prompt is stable across topics (prompt-cache friendly). User prompt
is per-topic. Bump PROMPT_VERSION whenever the system prompt changes
meaningfully — generation_metadata.prompt_version records it.
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pipeline.block_gen import TopicContext


PROMPT_VERSION = "agent3.v1"


SYSTEM_PROMPT = """\
You are generating teaching blocks for a mathematics topic in a structured learning system. Output is a single ordered JSON array of blocks that will be rendered in a BlockNote-based editor.

THREE LOCKED CONTRACTS

1. Anchor pinning by relative order. Pinned blocks listed under "PINNED ANCHORS" in the user prompt MUST appear in your output. Their `id` and `content` MUST be byte-identical to what you receive. Their absolute position in the new sequence is your choice. Their relative order with respect to each other MUST be preserved. Grouped anchors (sharing a `group_id`) MUST remain contiguous in the same internal order shown.

2. Atomic group coupling. Blocks that genuinely couple (a display equation and its explanation, a plot and its caption) share a `group_id`. Default is null. Use group_id sparingly. Once grouped, blocks in the cohort are never separated.

3. No citation text. You never write attributions, footnote markers, or parenthetical source references. When a block draws materially on a source chunk, populate `generation_metadata.source_chunk_ids` with the relevant chunk IDs. Citation rendering happens downstream.

BLOCK TYPES

paragraph        { type: "paragraph",        content: InlineContent[] }
heading          { type: "heading",          content: InlineContent[], props: { level: 1|2|3 } }
bulletListItem   { type: "bulletListItem",   content: InlineContent[] }
numberedListItem { type: "numberedListItem", content: InlineContent[] }
codeBlock        { type: "codeBlock",        content: [{ type: "text", text: string }], props: { language: string } }
callout          { type: "callout",          content: InlineContent[], props: { variant: "note"|"insight"|"warning" } }
math             { type: "math",             content: [], props: { mode: "display", latex: string, label?: string } }
plot             { type: "plot",             content: [], props: PlotSpec }

InlineContent (items inside a block's `content` array):
  { type: "text", text: string, styles?: { bold?: true, italic?: true, code?: true } }
  { type: "math", props: { latex: string } }                    // inline math
  { type: "link", href: string, content: InlineContent[] }

PlotSpec:
  {
    kind: "function2d" | "surface3d" | "levelcurves" | "vectorfield" | "parametric2d" | "parametric3d",
    expression: string | string[],
    domain: { x?: [number, number], y?: [number, number], t?: [number, number] },
    labels?: { x?: string, y?: string, z?: string, title?: string }
  }
Domain keys are kind-dependent: function2d requires domain.x; surface3d and levelcurves require domain.x and domain.y; parametric2d and parametric3d require domain.t.

OUTPUT FORMAT

Return a single JSON object, no prose preamble, no markdown fences:

{
  "blocks": [ ...ordered array of blocks... ]
}

Each newly generated (non-anchor) block may include:
  generation_metadata: { source_chunk_ids: string[] }
listing chunk IDs from the user prompt that materially grounded the block. Use an empty array when no chunks contributed.

Each anchor block in your output MUST include its `id` and `content` exactly as provided in PINNED ANCHORS. Do not include `generation_metadata` on anchors; their provenance is unchanged.
Pinned-anchor `content` is persisted BlockNote JSON and may be an object rather than the generated-block content array. Copy pinned anchor objects exactly; do not normalize them to the generated-block schema.

AUTHORING RULES

- Write teaching prose. Do not stitch chunk text together; chunks are background context, not source to be quoted.
- Prefer inline math for short equations embedded in sentences. Use display math blocks only when the equation deserves a line of its own.
- Emit plot blocks only when a visualization materially aids understanding. Default is no plot.
- Use group_id only when adjacency is genuinely required.
- Respect the relative order of pinned anchors and the internal order of grouped cohorts.
- Output language: English.
"""


def build_prompt(context: "TopicContext") -> tuple[str, str]:
    """Return (system, user) prompts. Pure, deterministic.

    Raises ValueError on sparse coverage. The orchestrator is expected to
    refuse before reaching this function; the check here is defense-in-depth.
    """
    if context.coverage == "sparse":
        raise ValueError(
            "build_prompt called on sparse-coverage topic; "
            "orchestrator must refuse before prompt construction"
        )
    return SYSTEM_PROMPT, _render_user_prompt(context)


def _render_user_prompt(context: "TopicContext") -> str:
    parts: list[str] = []
    pinned_cohorts = [c for c in context.cohorts if c.pinned]

    t = context.topic
    parts.append("TOPIC")
    parts.append(f"slug: {t.slug}")
    parts.append(f"title: {t.title}")
    parts.append(f"summary: {t.summary or '(none)'}")
    parts.append(f"course: {t.course_slug}")
    parts.append("")

    parts.append("PREREQUISITES (1-hop, already taught)")
    if not context.prereqs:
        parts.append("None.")
    else:
        for p in context.prereqs:
            summary = (p.summary or "").strip().replace("\n", " ")
            parts.append(f"- {p.slug} — {p.title}: {summary}")
    parts.append("")

    parts.append("SOURCE CHUNKS (top-K above similarity floor)")
    if not context.chunks:
        parts.append("None.")
    else:
        for c in context.chunks:
            src = _basename(c.source_path)
            page = f", p.{c.page_number}" if c.page_number else ""
            parts.append(
                f"[chunk_id={c.id}] (similarity={c.similarity:.3f}, source={src}{page})"
            )
            parts.append(c.content.strip())
            parts.append("---")
    parts.append("")

    parts.append(
        "PINNED ANCHORS "
        "(preserve `id` and `content` byte-identically; preserve relative order; "
        "keep grouped cohorts contiguous in the internal order shown)"
    )
    if not pinned_cohorts:
        parts.append("None — no manually-edited blocks on this topic.")
    else:
        for i, cohort in enumerate(pinned_cohorts, 1):
            header = (
                f"Cohort {i} (group_id={cohort.group_id})"
                if cohort.group_id is not None
                else f"Cohort {i} (singleton anchor)"
            )
            parts.append(header)
            for blk in cohort.blocks:
                anchor = {
                    "id": blk.id,
                    "type": blk.type,
                    "content": blk.content,
                    "group_id": blk.group_id,
                }
                parts.append("  Copy this anchor object exactly:")
                parts.append(
                    "  "
                    + json.dumps(
                        anchor,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
    parts.append("")

    parts.append("TASK")
    if pinned_cohorts:
        parts.append(
            "Generate the full ordered sequence of teaching blocks for this topic. "
            "Integrate every pinned anchor in the required relative order, with "
            "grouped cohorts kept contiguous. Output only the JSON object "
            "specified in the system prompt."
        )
    else:
        parts.append(
            "Generate the full ordered sequence of teaching blocks for this topic. "
            "Output only the JSON object specified in the system prompt."
        )

    return "\n".join(parts)


def _basename(path: str | None) -> str:
    """Filename for local paths; final URL segment for web (Agent 4) — adequate for v1."""
    if not path:
        return "(unknown)"
    return path.rsplit("/", 1)[-1]
