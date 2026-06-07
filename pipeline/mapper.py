"""
Agent 2: Prerequisite graph builder.

For each topic in a course, retrieve K nearest candidates via pgvector,
ask the LLM which are real prerequisites, validate, cycle-check, and write
TopicEdge rows to Postgres.
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass

import anthropic

from pipeline.db_guard import ensure_writable
from pipeline.db import (
    get_conn,
    nearest_topic_candidates,
    upsert_pipeline_state,
)
from pipeline.fingerprints import fingerprint_payload

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
K_CANDIDATES = 30
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("CLAUDE_MAPPER_TIMEOUT", "90"))

# Claude Sonnet pricing per million tokens. Update if model changes.
PRICE_IN = 3.00
PRICE_OUT = 15.00
CYCLE_DROP_FLOOR = 0.70

MANUAL_EXCLUDED_EDGES = {
    # MVC eval-grade false positives.
    ("mvc-chain-rule", "mvc-vector-calculus-ops"),
    ("mvc-quadric-surfaces", "mvc-parametric-curves"),
    ("mvc-dot-product", "mvc-parametric-curves"),
    ("mvc-lines-planes-3d", "mvc-multivariable-functions"),
    # Numerical computation: peer direction and "implemented in Matlab"
    # false positives that create cycles or reverse the tooling dependency.
    ("loss-of-significance", "floating-point-error-propagation"),
    ("ode-euler-heun-runge-kutta", "matlab-programming-numerical-methods"),
    ("bisection-method", "matlab-programming-numerical-methods"),
    ("newtons-method", "matlab-programming-numerical-methods"),
    ("numerical-integration-trapezoid-simpson", "matlab-programming-numerical-methods"),
    ("fixed-point-iteration", "matlab-programming-numerical-methods"),
    ("polynomial-interpolation-lagrange-newton", "matlab-programming-numerical-methods"),
    ("method-of-least-squares", "matlab-programming-numerical-methods"),
    # Data structures and algorithms: examples/applications mistaken for
    # prerequisites of the general theory topic, or reverse modeling links.
    ("dsa-binary-search", "dsa-divide-and-conquer-recurrences"),
    ("dsa-quicksort", "dsa-divide-and-conquer-recurrences"),
    ("dsa-graph-modeling", "dsa-max-flow"),
    ("dsa-kruskal", "dsa-mst-theory"),
    ("dsa-prim", "dsa-mst-theory"),
    # Operating systems: consistency checking is a validation/debugging aid
    # applied to malloc implementations, not a prerequisite for learning malloc.
    ("os-consistency-checking", "os-malloc"),
}

PROTECTED_EDGES = {
    ("os-page-faulting", "os-page-table-updates"),
    ("os-page-swapping", "os-page-faulting"),
    ("os-context-switching", "os-race-conditions"),
    ("os-processes-threads", "os-virtual-memory-page-tables"),
    ("os-mutex-synchronization", "os-race-conditions"),
}

AUDITED_DROP_EDGES = {
    ("os-page-table-updates", "os-page-swapping"),
    ("os-context-switching", "os-kernel-thread-models"),
    ("os-kernel-syscalls", "os-virtual-memory-page-tables"),
    ("os-race-conditions", "os-interrupt-handling"),
    ("os-virtual-memory-page-tables", "os-kernel-syscalls"),
    ("os-interrupt-handling", "os-kernel-syscalls"),
    ("os-filesystems", "os-io-devices"),
}


SYSTEM_PROMPT = """You identify prerequisite relationships between learning topics.

A prerequisite relationship is asymmetric and directional:
"A is a prerequisite of B" means a learner must understand A before B makes sense.

Examples:
- "partial derivatives" is a prerequisite of "multivariable chain rule" (you compose partials to apply the chain rule)
- "vectors in 3D" is a prerequisite of "cross product" (cross product is an operation on 3D vectors)
- "limits" is a prerequisite of "continuity" (continuity is defined via limits)

NOT prerequisites:
- Two topics that share vocabulary but neither depends on the other
- A topic that merely uses the same notation
- The reverse direction of a real prerequisite

If two topics are peers (both build on the same foundations but neither
builds on the other), they are NOT in a prerequisite relationship.
Example: "dot product" and "cross product" are peers — both build on
"vectors in 3D" but neither requires the other. Return no edge between peers.

You will see a TARGET topic and a list of CANDIDATE topics ranked by semantic similarity.
Your job: identify which candidates are genuine prerequisites of the target.

Return ONLY valid JSON in this shape:
{
  "prerequisites": [
    {"from_slug": "<candidate-slug>", "confidence": 0.0-1.0, "reason": "<one sentence>"}
  ]
}

Empty list is valid and expected for foundational topics.
Be strict. When in doubt, exclude. Confidence below 0.6 means exclude."""


@dataclass
class Edge:
    from_id: str
    to_id: str
    confidence: float
    reason: str


@dataclass(frozen=True)
class DroppedEdge:
    from_id: str
    to_id: str
    confidence: float
    reason: str
    drop_type: str


class CycleUnresolved(RuntimeError):
    def __init__(
        self,
        cycle: list[str],
        cycle_edges: list[Edge],
        *,
        id_to_slug: dict[str, str] | None = None,
    ) -> None:
        self.cycle = cycle
        self.cycle_edges = cycle_edges
        self.id_to_slug = id_to_slug or {}
        self.rendered_cycle = _render_cycle(cycle, self.id_to_slug)
        super().__init__(
            "No non-protected cycle edge below "
            f"{CYCLE_DROP_FLOOR:.2f}: {self.rendered_cycle}"
        )


def get_course_topics(course_slug: str) -> list[dict]:
    """Return all topics in a course with id, slug, title, summary."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute('SELECT id FROM "Course" WHERE slug = %s', (course_slug,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Course not found: {course_slug}")
        course_id = row[0]

        cur.execute(
            '''
            SELECT id, slug, title, summary
            FROM "Topic"
            WHERE "courseId" = %s
            ORDER BY "order"
            ''',
            (course_id,),
        )
        cols = [d[0] for d in cur.description]
        topics = [dict(zip(cols, r)) for r in cur.fetchall()]
        return course_id, topics


def build_user_prompt(target: dict, candidates: list[dict]) -> str:
    lines = [
        f"TARGET TOPIC:",
        f"  slug: {target['slug']}",
        f"  title: {target['title']}",
        f"  summary: {target.get('summary') or '(none)'}",
        "",
        f"CANDIDATES (ranked by semantic similarity, closer = more related but not necessarily prerequisite):",
        "",
    ]
    for c in candidates:
        lines.append(f"- slug: {c['slug']}")
        lines.append(f"  title: {c['title']}")
        lines.append(f"  summary: {c.get('summary') or '(none)'}")
        lines.append(f"  distance: {c['distance']:.4f}")
        lines.append("")
    lines.append("Which candidates are prerequisites of the target? Return JSON.")
    return "\n".join(lines)


def compute_fingerprint(topics: list[dict]) -> str:
    return fingerprint_payload(
        {
            "stage": "mapper.v1",
            "model": MODEL,
            "k_candidates": K_CANDIDATES,
            "system_prompt": SYSTEM_PROMPT,
            "manual_excluded_edges": sorted(MANUAL_EXCLUDED_EDGES),
            "protected_edges": sorted(PROTECTED_EDGES),
            "audited_drop_edges": sorted(AUDITED_DROP_EDGES),
            "cycle_drop_floor": CYCLE_DROP_FLOOR,
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


def parse_response(text: str) -> list[dict]:
    """Extract JSON from response. Hardened against fences and preamble."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in response: {text[:200]}")
    obj = json.loads(text[start : end + 1])
    return obj.get("prerequisites", [])


def detect_cycle(edges: list[Edge]) -> list[str] | None:
    """DFS cycle detection. Returns cycle path if found, else None."""
    graph: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        graph[e.from_id].append(e.to_id)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = defaultdict(lambda: WHITE)
    parent: dict[str, str | None] = {}

    def dfs(node: str) -> list[str] | None:
        color[node] = GRAY
        for nxt in graph[node]:
            if color[nxt] == GRAY:
                # Reconstruct cycle
                cycle = [nxt, node]
                cur = parent.get(node)
                while cur is not None and cur != nxt:
                    cycle.append(cur)
                    cur = parent.get(cur)
                cycle.append(nxt)
                return list(reversed(cycle))
            if color[nxt] == WHITE:
                parent[nxt] = node
                result = dfs(nxt)
                if result:
                    return result
        color[node] = BLACK
        return None

    for node in list(graph.keys()):
        if color[node] == WHITE:
            parent[node] = None
            result = dfs(node)
            if result:
                return result
    return None


def _cycle_edges(cycle: list[str], edges: list[Edge]) -> list[Edge]:
    by_pair = {(edge.from_id, edge.to_id): edge for edge in edges}
    cycle_edges: list[Edge] = []
    for i in range(len(cycle) - 1):
        pair = (cycle[i], cycle[i + 1])
        edge = by_pair.get(pair)
        if edge is None:
            raise ValueError(f"Cycle references missing edge {pair}")
        cycle_edges.append(edge)
    return cycle_edges


def _render_cycle(cycle: list[str], id_to_slug: dict[str, str]) -> str:
    return " -> ".join(id_to_slug.get(node, node) for node in cycle)


def _edge_pair(edge: Edge, id_to_slug: dict[str, str]) -> tuple[str, str]:
    return (
        id_to_slug.get(edge.from_id, edge.from_id),
        id_to_slug.get(edge.to_id, edge.to_id),
    )


def _drop_known_edges(
    edges: list[Edge],
    *,
    id_to_slug: dict[str, str],
) -> tuple[list[Edge], list[DroppedEdge]]:
    remaining: list[Edge] = []
    dropped: list[DroppedEdge] = []

    for edge in edges:
        pair = _edge_pair(edge, id_to_slug)
        if pair in AUDITED_DROP_EDGES:
            dropped.append(
                DroppedEdge(
                    from_id=edge.from_id,
                    to_id=edge.to_id,
                    confidence=edge.confidence,
                    reason=edge.reason,
                    drop_type="audited_drop",
                )
            )
            continue
        if pair in MANUAL_EXCLUDED_EDGES:
            dropped.append(
                DroppedEdge(
                    from_id=edge.from_id,
                    to_id=edge.to_id,
                    confidence=edge.confidence,
                    reason=edge.reason,
                    drop_type="manual_seed",
                )
            )
            continue
        remaining.append(edge)

    return remaining, dropped


def _resolve_mutual_edges(
    edges: list[Edge],
    *,
    id_to_slug: dict[str, str],
) -> tuple[list[Edge], list[DroppedEdge]]:
    by_pair = {(edge.from_id, edge.to_id): edge for edge in edges}
    consumed: set[tuple[str, str]] = set()
    resolved: list[Edge] = []
    dropped: list[DroppedEdge] = []

    for edge in edges:
        pair = (edge.from_id, edge.to_id)
        if pair in consumed:
            continue
        reverse_pair = (edge.to_id, edge.from_id)
        reverse_edge = by_pair.get(reverse_pair)
        if reverse_edge is None:
            resolved.append(edge)
            consumed.add(pair)
            continue

        consumed.add(pair)
        consumed.add(reverse_pair)
        pair_slug = _edge_pair(edge, id_to_slug)
        reverse_pair_slug = _edge_pair(reverse_edge, id_to_slug)

        if pair_slug in PROTECTED_EDGES and reverse_pair_slug not in PROTECTED_EDGES:
            keep_edge = edge
            drop_edge = reverse_edge
            drop_type = "reverse_protected"
            drop_reason = "spurious reverse of protected prerequisite"
        elif reverse_pair_slug in PROTECTED_EDGES and pair_slug not in PROTECTED_EDGES:
            keep_edge = reverse_edge
            drop_edge = edge
            drop_type = "reverse_protected"
            drop_reason = "spurious reverse of protected prerequisite"
        else:
            if (
                edge.confidence,
                id_to_slug.get(edge.from_id, edge.from_id),
                id_to_slug.get(edge.to_id, edge.to_id),
            ) >= (
                reverse_edge.confidence,
                id_to_slug.get(reverse_edge.from_id, reverse_edge.from_id),
                id_to_slug.get(reverse_edge.to_id, reverse_edge.to_id),
            ):
                keep_edge = edge
                drop_edge = reverse_edge
            else:
                keep_edge = reverse_edge
                drop_edge = edge
            drop_type = "mutual_lower_confidence"
            drop_reason = drop_edge.reason

        resolved.append(keep_edge)
        dropped.append(
            DroppedEdge(
                from_id=drop_edge.from_id,
                to_id=drop_edge.to_id,
                confidence=drop_edge.confidence,
                reason=drop_reason,
                drop_type=drop_type,
            )
        )

    return resolved, dropped


def _drop_reverse_protected_edges(
    edges: list[Edge],
    *,
    id_to_slug: dict[str, str],
) -> tuple[list[Edge], list[DroppedEdge]]:
    """Backward-compatible alias while callers migrate to mutual-edge resolution."""
    return _resolve_mutual_edges(edges, id_to_slug=id_to_slug)


def resolve_cycles(
    edges: list[Edge],
    *,
    id_to_slug: dict[str, str] | None = None,
    initial_dropped: list[DroppedEdge] | None = None,
) -> tuple[list[Edge], list[DroppedEdge]]:
    """Drop known bad edges first, then break only low-confidence unprotected cycles."""
    id_to_slug = id_to_slug or {}
    remaining, known_drops = _drop_known_edges(edges, id_to_slug=id_to_slug)
    remaining, mutual_drops = _resolve_mutual_edges(
        remaining, id_to_slug=id_to_slug
    )
    dropped: list[DroppedEdge] = list(initial_dropped or [])
    dropped.extend(known_drops)
    dropped.extend(mutual_drops)

    while True:
        cycle = detect_cycle(remaining)
        if not cycle:
            return remaining, dropped

        cycle_edges = _cycle_edges(cycle, remaining)
        droppable_edges = [
            edge
            for edge in cycle_edges
            if _edge_pair(edge, id_to_slug) not in PROTECTED_EDGES
        ]
        if not droppable_edges:
            raise CycleUnresolved(cycle, cycle_edges, id_to_slug=id_to_slug)

        weakest = min(
            droppable_edges,
            key=lambda edge: (
                edge.confidence,
                id_to_slug.get(edge.from_id, edge.from_id),
                id_to_slug.get(edge.to_id, edge.to_id),
            ),
        )
        if weakest.confidence >= CYCLE_DROP_FLOOR:
            raise CycleUnresolved(cycle, cycle_edges, id_to_slug=id_to_slug)
        dropped_edge = DroppedEdge(
            from_id=weakest.from_id,
            to_id=weakest.to_id,
            confidence=weakest.confidence,
            reason=weakest.reason,
            drop_type="cycle_collateral",
        )
        dropped.append(dropped_edge)
        remaining = [
            edge
            for edge in remaining
            if (edge.from_id, edge.to_id) != (weakest.from_id, weakest.to_id)
        ]
        from_slug = id_to_slug.get(weakest.from_id, weakest.from_id)
        to_slug = id_to_slug.get(weakest.to_id, weakest.to_id)
        print(
            "DROPPED CYCLE EDGE: "
            f"{from_slug} -> {to_slug} "
            f"(confidence={weakest.confidence:.2f}) "
            f"reason={weakest.reason}",
            file=sys.stderr,
        )


def _dropped_edges_metadata(
    dropped_edges: list[DroppedEdge],
    id_to_slug: dict[str, str],
) -> list[dict]:
    return [
        {
            "from_slug": id_to_slug.get(edge.from_id, edge.from_id),
            "to_slug": id_to_slug.get(edge.to_id, edge.to_id),
            "confidence": edge.confidence,
            "reason": edge.reason,
            "drop_type": edge.drop_type,
        }
        for edge in dropped_edges
    ]


def _persist_mapper_state(
    course_id: str,
    topics: list[dict],
    *,
    status: str,
    metadata: dict,
) -> None:
    upsert_pipeline_state(
        course_id,
        "mapper",
        "course",
        compute_fingerprint(topics),
        status,
        metadata,
    )


def extract_dependencies(
    course_slug: str,
    course_id: str,
    topics: list[dict],
) -> tuple[list[Edge], list[DroppedEdge], int, int]:
    """For each topic, retrieve candidates and ask LLM for prereqs."""
    client = anthropic.Anthropic(timeout=REQUEST_TIMEOUT_SECONDS)
    slug_to_id = {t["slug"]: t["id"] for t in topics}
    edges: list[Edge] = []
    dropped_edges: list[DroppedEdge] = []
    total_in = 0
    total_out = 0

    for i, target in enumerate(topics, 1):
        print(f"[{i}/{len(topics)}] {target['slug']}", end=" ... ", flush=True)

        candidates = nearest_topic_candidates(
            target["id"], k=K_CANDIDATES, course_id=course_id
        )
        # Only keep candidates that are in our topic set (defensive; should always be true when course-scoped)
        candidates = [c for c in candidates if c["slug"] in slug_to_id]

        if not candidates:
            print("no candidates")
            continue

        user_prompt = build_user_prompt(target, candidates)
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=2000,
                temperature=0,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.APIError as e:
            print(f"API FAIL: {type(e).__name__}: {e}")
            continue
        total_in += resp.usage.input_tokens
        total_out += resp.usage.output_tokens

        text = resp.content[0].text
        try:
            prereqs = parse_response(text)
        except (ValueError, json.JSONDecodeError) as e:
            print(f"PARSE FAIL: {e}")
            continue

        kept = 0
        for p in prereqs:
            from_slug = p.get("from_slug")
            conf = float(p.get("confidence", 0))
            reason = p.get("reason", "")

            if from_slug not in slug_to_id:
                continue  # hallucinated slug
            if from_slug == target["slug"]:
                continue  # self-edge
            if conf < 0.6:
                continue  # low confidence
            if (from_slug, target["slug"]) in MANUAL_EXCLUDED_EDGES:
                dropped_edges.append(
                    DroppedEdge(
                        from_id=slug_to_id[from_slug],
                        to_id=target["id"],
                        confidence=conf,
                        reason=reason,
                        drop_type="manual_seed",
                    )
                )
                continue
            if (from_slug, target["slug"]) in AUDITED_DROP_EDGES:
                dropped_edges.append(
                    DroppedEdge(
                        from_id=slug_to_id[from_slug],
                        to_id=target["id"],
                        confidence=conf,
                        reason=reason,
                        drop_type="audited_drop",
                    )
                )
                continue

            edges.append(
                Edge(
                    from_id=slug_to_id[from_slug],
                    to_id=target["id"],
                    confidence=conf,
                    reason=reason,
                )
            )
            kept += 1
        print(f"{kept} prereqs")

    # Dedup (same from_id, to_id pair) keeping highest confidence
    deduped: dict[tuple[str, str], Edge] = {}
    for e in edges:
        key = (e.from_id, e.to_id)
        if key not in deduped or e.confidence > deduped[key].confidence:
            deduped[key] = e
    edges = list(deduped.values())

    deduped_dropped: dict[tuple[str, str], DroppedEdge] = {}
    for edge in dropped_edges:
        key = (edge.from_id, edge.to_id)
        if key not in deduped_dropped or edge.confidence > deduped_dropped[key].confidence:
            deduped_dropped[key] = edge

    return edges, list(deduped_dropped.values()), total_in, total_out


def write_dependencies(edges: list[Edge], course_topic_ids: set[str]) -> None:
    """Idempotent: delete edges touching this course's topics, then bulk insert."""
    if not course_topic_ids:
        return
    ensure_writable()
    with get_conn() as conn, conn.cursor() as cur:
        ids = list(course_topic_ids)
        cur.execute(
            '''
            DELETE FROM "TopicEdge"
            WHERE "fromId" = ANY(%s) OR "toId" = ANY(%s)
            ''',
            (ids, ids),
        )
        deleted = cur.rowcount

        if edges:
            cur.executemany(
                '''
                INSERT INTO "TopicEdge" ("fromId", "toId", kind, confidence)
                VALUES (%s, %s, 'PREREQUISITE_OF', %s)
                ON CONFLICT ("fromId", "toId", kind) DO UPDATE
                  SET confidence = EXCLUDED.confidence
                ''',
                [(e.from_id, e.to_id, e.confidence) for e in edges],
            )
        conn.commit()
        print(f"deleted {deleted} old edges, inserted {len(edges)} new edges")


def run(course_slug: str, dry_run: bool = False) -> None:
    course_id, topics = get_course_topics(course_slug)
    print(f"course: {course_slug} ({len(topics)} topics)\n")
    id_to_slug = {t["id"]: t["slug"] for t in topics}
    edges: list[Edge] = []
    resolved_edges: list[Edge] = []
    dropped_edges: list[DroppedEdge] = []
    tok_in = 0
    tok_out = 0
    cost = 0.0

    try:
        edges, pre_dropped_edges, tok_in, tok_out = extract_dependencies(
            course_slug, course_id, topics
        )
        dropped_edges = list(pre_dropped_edges)
        cost = (tok_in * PRICE_IN + tok_out * PRICE_OUT) / 1_000_000
        resolved_edges, dropped_edges = resolve_cycles(
            edges,
            id_to_slug=id_to_slug,
            initial_dropped=dropped_edges,
        )
        print(f"\ntokens: {tok_in} in / {tok_out} out  cost: ${cost:.4f}")
        print(
            "total edges: "
            f"{len(edges)} raw / {len(resolved_edges)} after cycle resolution"
        )

        if dropped_edges:
            print("\ndropped mapper edges:\n", file=sys.stderr)
            for row in _dropped_edges_metadata(dropped_edges, id_to_slug):
                print(
                    f"  {row['from_slug']:<40} -> {row['to_slug']:<40} "
                    f"({row['confidence']:.2f}) [{row['drop_type']}] {row['reason']}",
                    file=sys.stderr,
                )

        if dry_run:
            print("\n--dry-run, edges that would be written:\n")
            for e in sorted(
                resolved_edges, key=lambda x: (id_to_slug[x.to_id], -x.confidence)
            ):
                print(
                    f"  {id_to_slug[e.from_id]:<40} -> {id_to_slug[e.to_id]:<40} "
                    f"({e.confidence:.2f})  {e.reason}"
                )
            return

        course_topic_ids = {t["id"] for t in topics}
        write_dependencies(resolved_edges, course_topic_ids)
        _persist_mapper_state(
            course_id,
            topics,
            status="ok",
            metadata={
                "topics": len(topics),
                "edges": len(resolved_edges),
                "raw_edges": len(edges),
                "input_tokens": tok_in,
                "output_tokens": tok_out,
                "usd_cost": cost,
                "dropped_edges": _dropped_edges_metadata(dropped_edges, id_to_slug),
            },
        )
    except Exception as exc:
        if not dry_run:
            metadata = {
                "topics": len(topics),
                "edges": len(resolved_edges),
                "raw_edges": len(edges),
                "input_tokens": tok_in,
                "output_tokens": tok_out,
                "usd_cost": cost,
                "dropped_edges": _dropped_edges_metadata(dropped_edges, id_to_slug),
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            if isinstance(exc, CycleUnresolved):
                metadata["cycle"] = exc.rendered_cycle
                metadata["cycle_edges"] = [
                    {
                        "from_slug": id_to_slug.get(edge.from_id, edge.from_id),
                        "to_slug": id_to_slug.get(edge.to_id, edge.to_id),
                        "confidence": edge.confidence,
                        "reason": edge.reason,
                        "protected": _edge_pair(edge, id_to_slug) in PROTECTED_EDGES,
                    }
                    for edge in exc.cycle_edges
                ]
            _persist_mapper_state(course_id, topics, status="failed", metadata=metadata)
        raise


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("course_slug")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    run(args.course_slug, dry_run=args.dry_run)
