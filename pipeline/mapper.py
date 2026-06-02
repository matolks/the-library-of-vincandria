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
)

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")
K_CANDIDATES = 30
REQUEST_TIMEOUT_SECONDS = float(os.environ.get("CLAUDE_MAPPER_TIMEOUT", "90"))

# Claude Sonnet pricing per million tokens. Update if model changes.
PRICE_IN = 3.00
PRICE_OUT = 15.00

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


def extract_dependencies(
    course_slug: str,
    course_id: str,
    topics: list[dict],
) -> tuple[list[Edge], int, int]:
    """For each topic, retrieve candidates and ask LLM for prereqs."""
    client = anthropic.Anthropic(timeout=REQUEST_TIMEOUT_SECONDS)
    slug_to_id = {t["slug"]: t["id"] for t in topics}
    edges: list[Edge] = []
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
                continue  # known false positive promoted from eval triage

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

    return edges, total_in, total_out


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

    edges, tok_in, tok_out = extract_dependencies(course_slug, course_id, topics)

    cost = (tok_in * PRICE_IN + tok_out * PRICE_OUT) / 1_000_000
    print(f"\ntokens: {tok_in} in / {tok_out} out  cost: ${cost:.4f}")
    print(f"total edges: {len(edges)}")

    id_to_slug = {t["id"]: t["slug"] for t in topics}

    if dry_run:
        print("\n--dry-run, edges that would be written:\n")
        for e in sorted(edges, key=lambda x: (id_to_slug[x.to_id], -x.confidence)):
            print(
                f"  {id_to_slug[e.from_id]:<40} -> {id_to_slug[e.to_id]:<40} "
                f"({e.confidence:.2f})  {e.reason}"
            )

    cycle = detect_cycle(edges)
    if cycle:
        path = " -> ".join(id_to_slug.get(n, n) for n in cycle)
        print(f"\nCYCLE DETECTED: {path}", file=sys.stderr)
        if not dry_run:
            sys.exit(1)
        return

    if dry_run:
        return

    course_topic_ids = {t["id"] for t in topics}
    write_dependencies(edges, course_topic_ids)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("course_slug")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    run(args.course_slug, dry_run=args.dry_run)
