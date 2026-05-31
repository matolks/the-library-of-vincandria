"""
Schema validation for generated blocks.

Pure function: dict -> list[str]. Empty list means the block conforms.
Error messages are written so they can be appended verbatim to a retry
prompt and acted on by the model.

Scope: structural shape only. Anchor-specific concerns (id preservation,
content byte-identity, relative ordering) live in validate_anchor_integrity.
"""
from __future__ import annotations


BLOCK_TYPES: frozenset[str] = frozenset({
    "paragraph", "heading", "bulletListItem", "numberedListItem",
    "codeBlock", "callout", "math", "plot", "image",
})

HEADING_LEVELS: frozenset[int] = frozenset({1, 2, 3})
CALLOUT_VARIANTS: frozenset[str] = frozenset({"note", "insight", "warning"})
PLOT_KINDS: frozenset[str] = frozenset({
    "function2d", "surface3d", "levelcurves", "vectorfield",
    "parametric2d", "parametric3d",
})

# Required domain keys per plot kind.
# NOTE: §3 of AGENT3_DESIGN.md is silent on vectorfield's required keys.
# Defaulting to {x, y} (2D vectorfield, the common case). Tighten when the
# design clarifies; if 3D vectorfields land, add a kind discriminator.
PLOT_DOMAIN_KEYS: dict[str, frozenset[str]] = {
    "function2d":   frozenset({"x"}),
    "surface3d":    frozenset({"x", "y"}),
    "levelcurves":  frozenset({"x", "y"}),
    "vectorfield":  frozenset({"x", "y"}),
    "parametric2d": frozenset({"t"}),
    "parametric3d": frozenset({"t"}),
}

INLINE_STYLE_KEYS: frozenset[str] = frozenset({"bold", "italic", "code"})


def validate_block_schema(block: dict) -> list[str]:
    """Return [] if block matches its BlockType contract, else error messages."""
    if not isinstance(block, dict):
        return [f"block is not an object: got {type(block).__name__}"]

    btype = block.get("type")
    if btype not in BLOCK_TYPES:
        return [
            f"block.type {btype!r} is not a valid BlockType "
            f"(allowed: {sorted(BLOCK_TYPES)})"
        ]

    errs: list[str] = []
    content = block.get("content")
    props = block.get("props", {})
    if not isinstance(props, dict):
        errs.append(f"{btype}: props must be an object, got {type(props).__name__}")
        props = {}

    if btype in ("paragraph", "bulletListItem", "numberedListItem"):
        errs += _validate_inline_array(content, btype)

    elif btype == "heading":
        errs += _validate_inline_array(content, btype)
        level = props.get("level")
        if level not in HEADING_LEVELS:
            errs.append(f"heading.props.level must be 1, 2, or 3; got {level!r}")

    elif btype == "codeBlock":
        errs += _validate_code_content(content)
        lang = props.get("language")
        if not isinstance(lang, str) or not lang:
            errs.append(
                f"codeBlock.props.language must be a non-empty string; got {lang!r}"
            )

    elif btype == "callout":
        errs += _validate_inline_array(content, btype)
        variant = props.get("variant")
        if variant not in CALLOUT_VARIANTS:
            errs.append(
                f"callout.props.variant must be one of {sorted(CALLOUT_VARIANTS)}; "
                f"got {variant!r}"
            )

    elif btype == "math":
        if content != []:
            errs.append(f"math.content must be an empty array, got {content!r}")
        mode = props.get("mode")
        latex = props.get("latex")
        if mode != "display":
            errs.append(f'math.props.mode must be "display"; got {mode!r}')
        if not isinstance(latex, str) or not latex.strip():
            errs.append(f"math.props.latex must be a non-empty string; got {latex!r}")
        elif "$" in latex:
            errs += _validate_latex_no_dollar(latex, "math.props.latex")
        if "label" in props and not isinstance(props["label"], str):
            errs.append(
                f"math.props.label, if present, must be a string; "
                f"got {type(props['label']).__name__}"
            )

    elif btype == "plot":
        if content != []:
            errs.append(f"plot.content must be an empty array, got {content!r}")
        errs += _validate_plot_props(props)

    elif btype == "image":
        if content != []:
            errs.append(f"image.content must be an empty array, got {content!r}")
        errs += _validate_image_props(props)

    if "generation_metadata" in block and block["generation_metadata"] is not None:
        errs += _validate_generation_metadata(block["generation_metadata"])

    return errs


# ---- helpers --------------------------------------------------------------


def _validate_inline_array(content, btype: str) -> list[str]:
    if not isinstance(content, list):
        return [
            f"{btype}.content must be an array of InlineContent items; "
            f"got {type(content).__name__}"
        ]
    errs: list[str] = []
    for i, item in enumerate(content):
        errs += _validate_inline_item(item, f"{btype}.content[{i}]")
    return errs


def _validate_inline_item(item, path: str) -> list[str]:
    if not isinstance(item, dict):
        return [f"{path} must be an object; got {type(item).__name__}"]
    itype = item.get("type")
    if itype == "text":
        if not isinstance(item.get("text"), str):
            return [f"{path}: text inline item missing string `text`"]
        styles = item.get("styles")
        if styles is not None:
            if not isinstance(styles, dict):
                return [f"{path}.styles must be an object if present"]
            bad = set(styles) - INLINE_STYLE_KEYS
            if bad:
                return [
                    f"{path}.styles has unknown keys {sorted(bad)}; "
                    f"allowed: {sorted(INLINE_STYLE_KEYS)}"
                ]
        return []
    if itype == "math":
        props = item.get("props")
        if not isinstance(props, dict) or not isinstance(props.get("latex"), str):
            return [f"{path}: inline math missing `props.latex` string"]
        return _validate_latex_no_dollar(props["latex"], f"{path}.props.latex")
    if itype == "link":
        href = item.get("href")
        if not isinstance(href, str) or not href:
            return [f"{path}: link missing non-empty `href` string"]
        inner = item.get("content")
        if not isinstance(inner, list):
            return [f"{path}.content must be an InlineContent array"]
        errs: list[str] = []
        for j, sub in enumerate(inner):
            errs += _validate_inline_item(sub, f"{path}.content[{j}]")
        return errs
    return [f"{path}: unknown inline type {itype!r} (allowed: text, math, link)"]


def _validate_code_content(content) -> list[str]:
    if not isinstance(content, list) or len(content) != 1:
        return [
            'codeBlock.content must be a single-element array: '
            '[{type: "text", text: string}]'
        ]
    item = content[0]
    if (
        not isinstance(item, dict)
        or item.get("type") != "text"
        or not isinstance(item.get("text"), str)
    ):
        return ['codeBlock.content[0] must be {type: "text", text: string}']
    return []


def _validate_plot_props(props: dict) -> list[str]:
    errs: list[str] = []
    kind = props.get("kind")
    if kind not in PLOT_KINDS:
        return [f"plot.props.kind must be one of {sorted(PLOT_KINDS)}; got {kind!r}"]

    expr = props.get("expression")
    if isinstance(expr, str):
        if not expr.strip():
            errs.append("plot.props.expression must be a non-empty string")
    elif isinstance(expr, list):
        if not expr or not all(isinstance(e, str) and e.strip() for e in expr):
            errs.append(
                "plot.props.expression array must contain only non-empty strings"
            )
    else:
        errs.append(
            f"plot.props.expression must be a string or array of strings; "
            f"got {type(expr).__name__}"
        )

    domain = props.get("domain")
    if not isinstance(domain, dict):
        errs.append(f"plot.props.domain must be an object; got {type(domain).__name__}")
    else:
        required = PLOT_DOMAIN_KEYS[kind]
        missing = required - set(domain)
        if missing:
            errs.append(
                f"plot.props.domain for kind {kind!r} is missing required "
                f"key(s) {sorted(missing)}"
            )
        for key in ("x", "y", "z", "t"):
            if key in domain:
                rng = domain[key]
                if (
                    not isinstance(rng, list)
                    or len(rng) != 2
                    or not all(isinstance(n, (int, float)) and not isinstance(n, bool) for n in rng)
                    or rng[0] >= rng[1]
                ):
                    errs.append(
                        f"plot.props.domain.{key} must be [low, high] with low < high; "
                        f"got {rng!r}"
                    )

    labels = props.get("labels")
    if labels is not None:
        if not isinstance(labels, dict):
            errs.append("plot.props.labels must be an object if present")
        else:
            bad = set(labels) - {"x", "y", "z", "title"}
            if bad:
                errs.append(
                    f"plot.props.labels has unknown keys {sorted(bad)}; "
                    f"allowed: x, y, z, title"
                )
            for k, v in labels.items():
                if not isinstance(v, str):
                    errs.append(f"plot.props.labels.{k} must be a string")

    return errs


def _validate_image_props(props: dict) -> list[str]:
    errs: list[str] = []
    src = props.get("src")
    alt = props.get("alt")
    if not isinstance(src, str) or not src.strip():
        errs.append(f"image.props.src must be a non-empty string; got {src!r}")
    if not isinstance(alt, str) or not alt.strip():
        errs.append(f"image.props.alt must be a non-empty string; got {alt!r}")
    if "caption" in props and not isinstance(props["caption"], str):
        errs.append(
            f"image.props.caption, if present, must be a string; "
            f"got {type(props['caption']).__name__}"
        )
    if "width" in props:
        width = props["width"]
        if not isinstance(width, (int, float)) or isinstance(width, bool) or width <= 0:
            errs.append(
                f"image.props.width, if present, must be a positive number; "
                f"got {width!r}"
            )
    bad = set(props) - {"src", "alt", "caption", "width"}
    if bad:
        errs.append(
            f"image.props has unknown keys {sorted(bad)}; "
            "allowed: src, alt, caption, width"
        )
    return errs


def _validate_generation_metadata(meta) -> list[str]:
    if not isinstance(meta, dict):
        return [
            f"generation_metadata must be an object if present; "
            f"got {type(meta).__name__}"
        ]
    ids = meta.get("source_chunk_ids")
    if not isinstance(ids, list):
        return ["generation_metadata.source_chunk_ids must be an array of strings"]
    if not all(isinstance(i, str) for i in ids):
        return ["generation_metadata.source_chunk_ids must contain only strings"]
    return []


def _validate_latex_no_dollar(latex: str, path: str) -> list[str]:
    if "$" in latex:
        return [
            f"{path} must contain raw LaTeX without dollar delimiters; "
            f"got {latex!r}"
        ]
    return []
