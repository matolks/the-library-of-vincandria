"""
Content quality judge for generated teaching blocks.

Runs after block_gen to flag mechanical content issues: missing plots, broken
plot specs, ungrouped equation+caption pairs, generic prose, suspicious facts,
prereq gaps, confusing transitions.

Cannot evaluate teaching quality — that needs a human reading as a learner.
This is a mechanical pre-filter to surface obvious failures cheaply.

Usage:
    python -m pipeline.judge --course multivariable-calculus
    python -m pipeline.judge --course multivariable-calculus --topic mvc-quadric-surfaces
    python -m pipeline.judge --course multivariable-calculus --output reports/mvc.json
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import anthropic

from pipeline import db
from pipeline.block_gen import ExistingBlock, TopicContext, get_topic_context
from pipeline.llm import DEFAULT_MODEL, PRICING_USD_PER_MTOK


PROMPT_VERSION = "judge.v4"

CATEGORIES = (
    "factual_error",
    "prereq_gap",
    "missing_plot",
    "broken_plot_spec",
    "missing_group",
    "generic_prose",
    "confusing_transition",
)
SEVERITIES = ("low", "medium", "high")


@dataclass(frozen=True)
class JudgeFinding:
    category: str
    severity: str
    block_id: str | None  # None for topic-level findings
    description: str
    suggested_fix: str | None = None


@dataclass(frozen=True)
class JudgeResult:
    topic_id: str
    topic_slug: str
    findings: tuple[JudgeFinding, ...]
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    usd_cost: float
    status: str  # "ok" | "no_blocks" | "parse_failed"
    error: str | None = None


# ---- prompt ---------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a content-quality judge for an AI-generated mathematics learning system. You evaluate one topic at a time and emit structured findings about mechanical content issues. You do NOT rewrite blocks. You do NOT comment on teaching style or learner experience. You catch only the things below.

CATEGORIES (use exactly these strings; never invent new ones)

factual_error
  A generated mathematical claim that is actually wrong, OR a generated claim that contradicts the SOURCE CHUNKS. Wrong formula, wrong direction of implication, swapped variables, contradicted definition. Style issues are NOT factual errors.
  Guardrails:
  - Evaluate the generated BLOCK SEQUENCE, not the source chunks. If a source chunk contains an error but the generated block does not repeat it, do not flag it.
  - Do not flag a factual_error because a block is merely less precise than a source chunk unless it becomes false or misleading.
  - If your own reasoning concludes the generated statement is correct, omit the finding.
  - A plot showing one explicitly labeled branch, cap, or sheet is not a factual error merely because a fuller implicit surface would have another branch.

prereq_gap
  A concept is used as if known but is not in the listed prerequisites and is not introduced in this topic before use. Only flag if a learner with exactly the listed prereqs would be confused.

missing_plot
  The prose is describing a specific geometric object (a surface, region, curve, vector field, level set, or named example) that the reader would need to visualize, and no plot block accompanies it. Do NOT flag for purely algebraic content (chain rule, product rule, definitions without concrete domain). Specific cases to flag:
  - A topic enumerating distinct surfaces (e.g., ellipsoid, paraboloid, hyperboloid) without one plot per form.
  - A worked example using a specific function whose shape matters and no plot.
  - A region of integration described in words with no plot.
  - A parametric path described without a plot.
  Renderer guardrail: today only function2d and surface3d render as full visuals. Do NOT flag missing_plot when the honest visualization would require an unsupported kind or diagram, such as parametric2d/3d, vectorfield, shaded regions, 3D vector arrows, implicit surfaces, intersections of multiple objects, or graph/diagram drawings. Flag only when a function2d or surface3d plot can directly and honestly show the object being discussed. A spec-preview-only plot does not satisfy a missing_plot, but a missing unsupported plot is infrastructure debt, not a content finding.
  Quadric guardrail: do NOT flag a missing_plot for a hyperboloid of one sheet in standard form x^2/a^2 + y^2/b^2 - z^2/c^2 = 1. A surface3d block is z=f(x,y), so any honest plot is double-valued or has a hole in the middle; the common z=sqrt(c^2*(1 + x^2/a^2 + y^2/b^2)) formula is a hyperboloid of two sheets, not one sheet.
  Duplication guardrail: do NOT flag a worked example merely because it names a specific surface if the same surface family was already plotted in the topic and the example is about algebraic classification or traces rather than a new visual feature.

broken_plot_spec
  A plot block whose expression won't evaluate. Common issues:
  - Uses Math.x prefix (must be bare mathjs names: sqrt, sin, cos, max, etc.).
  - Uses ** for exponentiation (must be ^).
  - References a variable not in the domain keys for that kind (e.g., function2d using y).
  - Domain interval has low >= high.
  - Expression is structurally malformed for the kind.
  Before flagging a square-root or logarithm domain issue, check the declared domain. If the expression is valid over the declared domain, do not flag it. If only part of the rectangular grid is undefined but the renderer can still draw finite points, flag only when the plot would materially misrepresent the surface.

missing_group
  Two adjacent blocks are coupled by meaning but share no group_id. Flag ONLY:
  - A display math block immediately followed by a paragraph that explicitly interprets that exact equation, defines its symbols, or explains the formula's geometric meaning.
  - A plot block immediately followed by a paragraph that names visible features of that plot ("The saddle at the origin", "Notice the ridge along x=0").
  - A worked-example math block followed by paragraph(s) walking through that specific computation.
  Do NOT flag paragraphs that merely follow an equation in topic order without interpreting it.

generic_prose
  A block that reads like a generic textbook gloss with no specific content unique to the topic — "It is important to understand X", "X has many applications in science and engineering", boilerplate openers and closers. Flag only when the block could be deleted without losing information.

confusing_transition
  Two consecutive blocks have a logical leap a learner would stumble on — an unstated intermediate step, a sudden notation change, a switch of variables without warning. Reference both block_ids in the description.

SEVERITIES

high      Materially wrong or actively misleading. Factual errors are usually high. Missing plots on geometry-centric topics are usually high.
medium    Will degrade understanding but won't mislead. Broken plot specs are medium (the renderer hides the issue but the spec is still wrong). Missing groups are medium.
low       Style or polish. Generic prose, mild confusing transitions.

OUTPUT FORMAT

Return a single JSON object, no prose preamble, no markdown fences:

{
  "findings": [
    {
      "category": "<one of CATEGORIES>",
      "severity": "<one of SEVERITIES>",
      "block_id": "<block id from the BLOCK SEQUENCE, or null for topic-level>",
      "description": "<one-sentence specific description naming the issue>",
      "suggested_fix": "<optional one-sentence concrete fix, or null>"
    }
  ]
}

If there are no findings, return {"findings": []}.

PLOT EXPRESSION DIALECT (reference for broken_plot_spec)
- mathjs, not JavaScript
- Bare function names: sqrt, sin, cos, tan, exp, log, abs, min, max, pow, atan2
- Constants: pi, e
- Power operator is ^ (not **)
- No Math. prefix anywhere
- Variables limited to domain keys: function2d uses x; surface3d/levelcurves use x and y; parametric* use t

PRINCIPLE

Be specific. Every finding names a concrete block or pair of blocks and says exactly what is wrong. Do not flag style preferences. Do not invent issues to look thorough. An empty findings array is a valid response when the topic is clean.

Before emitting each finding, perform a final sanity check: if your description would say the block is "actually correct", "mathematically correct", "fine", "safe", "not broken", "valid", or "not an issue", omit the finding entirely. Never include a self-contradictory finding.
"""


# ---- block rendering for the prompt ---------------------------------------

def _flatten_inline(items) -> str:
    if not items:
        return ""
    out: list[str] = []
    for item in items:
        t = item.get("type")
        if t == "text":
            out.append(item.get("text", ""))
        elif t == "math":
            latex = item.get("props", {}).get("latex", "")
            out.append(f"${latex}$")
        elif t == "link":
            out.append(_flatten_inline(item.get("content")))
    return "".join(out)


def _render_block(b: ExistingBlock) -> str:
    content = b.content or {}
    props = content.get("props", {}) if isinstance(content, dict) else {}
    inner = content.get("content") if isinstance(content, dict) else None
    gid = f" group={b.group_id}" if b.group_id else ""
    head = f"[id={b.id}{gid}]"

    if b.type == "paragraph":
        return f"{head} paragraph: {_flatten_inline(inner)}"
    if b.type == "heading":
        level = props.get("level", 2)
        return f"{head} heading: {'#' * level} {_flatten_inline(inner)}"
    if b.type == "bulletListItem":
        return f"{head} bullet: - {_flatten_inline(inner)}"
    if b.type == "numberedListItem":
        return f"{head} numbered: 1. {_flatten_inline(inner)}"
    if b.type == "codeBlock":
        lang = props.get("language", "")
        text = inner[0].get("text", "") if inner else ""
        return f"{head} codeBlock ({lang}):\n{text}"
    if b.type == "callout":
        variant = props.get("variant", "note")
        return f"{head} callout ({variant}): {_flatten_inline(inner)}"
    if b.type == "math":
        latex = props.get("latex", "")
        label = props.get("label")
        suffix = f"  ({label})" if label else ""
        return f"{head} display-math: $${latex}$${suffix}"
    if b.type == "plot":
        return (
            f"{head} plot: kind={props.get('kind', '?')} "
            f"expression={json.dumps(props.get('expression', ''))} "
            f"domain={json.dumps(props.get('domain', {}))} "
            f"labels={json.dumps(props.get('labels', {}))}"
        )
    return f"{head} {b.type}: <unrenderable>"


def _read_topic_blocks(topic_id: str) -> list[ExistingBlock]:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT id, "order", type, content, group_id, manually_edited, generation_metadata
            FROM "Block"
            WHERE "topicId" = %s
            ORDER BY "order"
            ''',
            (topic_id,),
        )
        rows = cur.fetchall()
    out: list[ExistingBlock] = []
    for r in rows:
        content = r[3] if isinstance(r[3], dict) else (json.loads(r[3]) if r[3] else {})
        gm = r[6] if isinstance(r[6], dict) else (json.loads(r[6]) if r[6] else None)
        out.append(ExistingBlock(
            id=r[0], order=r[1], type=r[2], content=content,
            group_id=r[4], manually_edited=r[5], generation_metadata=gm,
        ))
    return out


def _build_user_prompt(context: TopicContext, blocks: list[ExistingBlock]) -> str:
    parts: list[str] = []
    t = context.topic
    parts.append("TOPIC")
    parts.append(f"slug: {t.slug}")
    parts.append(f"title: {t.title}")
    parts.append(f"summary: {t.summary or '(none)'}")
    parts.append("")

    parts.append("PREREQUISITES (concepts the learner already knows)")
    if not context.prereqs:
        parts.append("None.")
    else:
        for p in context.prereqs:
            parts.append(f"- {p.slug} — {p.title}")
    parts.append("")

    parts.append("SOURCE CHUNKS (for fact-checking claims; not for style)")
    if not context.chunks:
        parts.append("None.")
    else:
        for c in context.chunks:
            parts.append(f"[chunk={c.id[:8]} sim={c.similarity:.2f}]")
            parts.append(c.content.strip())
            parts.append("---")
    parts.append("")

    parts.append("BLOCK SEQUENCE (this is what to evaluate; in topic order)")
    if not blocks:
        parts.append("(no blocks)")
    else:
        for b in blocks:
            parts.append(_render_block(b))
    parts.append("")

    parts.append("TASK")
    parts.append(
        "Emit the JSON object specified in the system prompt. List every finding "
        "you have evidence for. Use block_id from the BLOCK SEQUENCE for "
        "block-level findings; use null for topic-level findings."
    )
    return "\n".join(parts)


# ---- LLM call + parse -----------------------------------------------------

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def _parse_findings(raw: str) -> list[JudgeFinding]:
    text = _FENCE_RE.sub("", raw).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = _parse_first_json_object(text)
    if not isinstance(parsed, dict):
        raise ValueError(f"root must be object, got {type(parsed).__name__}")
    findings_raw = parsed.get("findings")
    if not isinstance(findings_raw, list):
        raise ValueError("missing or non-array `findings`")
    out: list[JudgeFinding] = []
    for i, f in enumerate(findings_raw):
        if not isinstance(f, dict):
            raise ValueError(f"findings[{i}] is not an object")
        cat = f.get("category")
        sev = f.get("severity")
        if cat not in CATEGORIES:
            raise ValueError(f"findings[{i}].category={cat!r} not in {CATEGORIES}")
        if sev not in SEVERITIES:
            raise ValueError(f"findings[{i}].severity={sev!r} not in {SEVERITIES}")
        finding = JudgeFinding(
            category=cat, severity=sev,
            block_id=f.get("block_id"),
            description=str(f.get("description", "")),
            suggested_fix=f.get("suggested_fix"),
        )
        if _is_self_contradictory_finding(finding):
            continue
        out.append(finding)
    return out


_SELF_CONTRADICTORY_RE = re.compile(
    r"\b("
    r"actually correct|mathematically correct|is correct|are correct|"
    r"not incorrect|not wrong|not broken|not an issue|no issue|"
    r"valid as written|safe as written|does not need|no fix needed|"
    r"this is fine|is fine"
    r")\b",
    re.IGNORECASE,
)


def _is_self_contradictory_finding(finding: JudgeFinding) -> bool:
    text = f"{finding.description} {finding.suggested_fix or ''}"
    return bool(_SELF_CONTRADICTORY_RE.search(text))


def _parse_first_json_object(text: str):
    """Parse the first JSON object in a response with stray leading/trailing text."""
    start = text.find("{")
    if start == -1:
        raise ValueError("no JSON object found in response")
    decoder = json.JSONDecoder()
    candidate = text[start:]
    try:
        parsed, _ = decoder.raw_decode(candidate)
        return parsed
    except json.JSONDecodeError:
        repaired = _repair_jsonish(candidate)
        parsed, _ = decoder.raw_decode(repaired)
        return parsed


def _repair_jsonish(text: str) -> str:
    """Best-effort repair for nearly-JSON model output with bare keys/trailing commas."""
    repaired = re.sub(r"(?<=[{,])\s*([A-Za-z_][A-Za-z0-9_]*)\s*:", r'"\1":', text)
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    return repaired


def judge_topic(
    topic_id: str,
    *,
    model: str = DEFAULT_MODEL,
    client: anthropic.Anthropic | None = None,
) -> JudgeResult:
    client = client or anthropic.Anthropic()
    context = get_topic_context(topic_id)
    blocks = _read_topic_blocks(topic_id)

    if not blocks:
        return JudgeResult(
            topic_id=topic_id, topic_slug=context.topic.slug,
            findings=(), model=model,
            input_tokens=0, output_tokens=0,
            cache_creation_tokens=0, cache_read_tokens=0,
            usd_cost=0.0, status="no_blocks",
        )

    user = _build_user_prompt(context, blocks)

    response = client.messages.create(
        model=model,
        max_tokens=8000,
        temperature=0,
        system=[{
            "type": "text",
            "text": SYSTEM_PROMPT,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user}],
    )

    raw = "".join(
        b.text for b in response.content if getattr(b, "type", None) == "text"
    ).strip()

    u = response.usage
    cache_create = getattr(u, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(u, "cache_read_input_tokens", 0) or 0
    rates = PRICING_USD_PER_MTOK.get(model, {})
    cost = (
        u.input_tokens * rates.get("input", 0)
        + u.output_tokens * rates.get("output", 0)
        + cache_create * rates.get("cache_write", 0)
        + cache_read * rates.get("cache_read", 0)
    ) / 1_000_000

    try:
        findings = _parse_findings(raw)
        status, error = "ok", None
    except (json.JSONDecodeError, ValueError) as e:
        findings, status, error = [], "parse_failed", f"{type(e).__name__}: {e}"

    return JudgeResult(
        topic_id=topic_id, topic_slug=context.topic.slug,
        findings=tuple(findings), model=model,
        input_tokens=u.input_tokens, output_tokens=u.output_tokens,
        cache_creation_tokens=cache_create, cache_read_tokens=cache_read,
        usd_cost=cost, status=status, error=error,
    )


# ---- CLI ------------------------------------------------------------------

def _resolve_targets(course_slug: str, topic_slug: str | None) -> list[tuple[str, str]]:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT t.id, t.slug
            FROM "Topic" t
            JOIN "Course" c ON c.id = t."courseId"
            WHERE c.slug = %s
              AND (%s::text IS NULL OR t.slug = %s)
            ORDER BY t."order"
            ''',
            (course_slug, topic_slug, topic_slug),
        )
        rows = cur.fetchall()
    if not rows:
        raise SystemExit(
            f"no topics found for course={course_slug!r}"
            + (f" topic={topic_slug!r}" if topic_slug else "")
        )
    return [(r[0], r[1]) for r in rows]


def _summarize(result: JudgeResult) -> str:
    by_cat: dict[str, int] = {}
    by_sev: dict[str, int] = {}
    for f in result.findings:
        by_cat[f.category] = by_cat.get(f.category, 0) + 1
        by_sev[f.severity] = by_sev.get(f.severity, 0) + 1
    cat_str = ", ".join(f"{k}={v}" for k, v in sorted(by_cat.items())) or "none"
    sev_str = ", ".join(f"{k}={v}" for k, v in sorted(by_sev.items())) or "none"
    return (
        f"{result.topic_slug}: status={result.status} findings={len(result.findings)} "
        f"[{sev_str}] [{cat_str}] cost=${result.usd_cost:.4f}"
    )


def _main() -> None:
    p = argparse.ArgumentParser(description="Mechanical judge for generated teaching blocks.")
    p.add_argument("--course", required=True, help="course slug")
    p.add_argument("--topic", help="optional topic slug for a single-topic run")
    p.add_argument("--output", help="output JSON path (default: reports/judge_<course>_<ts>.json)")
    p.add_argument("--pause-seconds", type=float, default=0.0)
    p.add_argument("--model", default=DEFAULT_MODEL)
    args = p.parse_args()

    targets = _resolve_targets(args.course, args.topic)

    if args.output:
        out_path = pathlib.Path(args.output)
    else:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = pathlib.Path("reports") / f"judge_{args.course}_{ts}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    results: list[JudgeResult] = []
    totals = {"findings": 0, "cost": 0.0, "in": 0, "out": 0, "cache_create": 0, "cache_read": 0}
    sev_totals = {"low": 0, "medium": 0, "high": 0}

    client = anthropic.Anthropic()
    try:
        for i, (topic_id, slug) in enumerate(targets):
            if i and args.pause_seconds > 0:
                time.sleep(args.pause_seconds)
            try:
                result = judge_topic(topic_id, model=args.model, client=client)
            except Exception as e:
                print(f"{slug}: ERROR {type(e).__name__}: {e}")
                continue
            results.append(result)
            print(_summarize(result))
            totals["findings"] += len(result.findings)
            totals["cost"] += result.usd_cost
            totals["in"] += result.input_tokens
            totals["out"] += result.output_tokens
            totals["cache_create"] += result.cache_creation_tokens
            totals["cache_read"] += result.cache_read_tokens
            for f in result.findings:
                sev_totals[f.severity] += 1
    finally:
        db.close()

    report = {
        "course_slug": args.course,
        "judge_version": PROMPT_VERSION,
        "model": args.model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topics": [
            {
                **{k: v for k, v in asdict(r).items() if k != "findings"},
                "findings": [asdict(f) for f in r.findings],
            }
            for r in results
        ],
        "totals": {**totals, **{f"severity_{k}": v for k, v in sev_totals.items()}},
    }
    out_path.write_text(json.dumps(report, indent=2))
    print()
    print(
        f"TOTAL: topics={len(results)} findings={totals['findings']} "
        f"(high={sev_totals['high']} medium={sev_totals['medium']} low={sev_totals['low']}) "
        f"cost=${totals['cost']:.4f}"
    )
    print(f"wrote {out_path}")


if __name__ == "__main__":
    _main()
