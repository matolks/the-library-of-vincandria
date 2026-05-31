"""
Query prerequisite graph: 1-hop and transitive prereqs for a topic.
Confirms TopicEdge data is queryable via recursive CTE.
"""

import sys
from pipeline.db import get_conn


def one_hop(slug: str) -> list[dict]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            '''
            SELECT t.slug, t.title, e.confidence
            FROM "TopicEdge" e
            JOIN "Topic" target ON target.id = e."toId"
            JOIN "Topic" t      ON t.id      = e."fromId"
            WHERE target.slug = %s
              AND e.kind = 'PREREQUISITE_OF'
            ORDER BY e.confidence DESC
            ''',
            (slug,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def transitive(slug: str) -> list[dict]:
    """All ancestors (recursive prereqs) of a topic, with depth."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            '''
            WITH RECURSIVE ancestors AS (
                SELECT e."fromId" AS id, 1 AS depth
                FROM "TopicEdge" e
                JOIN "Topic" t ON t.id = e."toId"
                WHERE t.slug = %s
                  AND e.kind = 'PREREQUISITE_OF'

                UNION

                SELECT e."fromId", a.depth + 1
                FROM "TopicEdge" e
                JOIN ancestors a ON a.id = e."toId"
                WHERE e.kind = 'PREREQUISITE_OF'
            )
            SELECT t.slug, t.title, MIN(a.depth) AS depth
            FROM ancestors a
            JOIN "Topic" t ON t.id = a.id
            GROUP BY t.slug, t.title
            ORDER BY depth, t.slug
            ''',
            (slug,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m scripts.query_prereqs <topic-slug>")
        sys.exit(1)
    slug = sys.argv[1]

    direct = one_hop(slug)
    print(f"\nDirect prerequisites of '{slug}':\n")
    if not direct:
        print("  (none)")
    for r in direct:
        print(f"  {r['confidence']:.2f}  {r['slug']:<40} {r['title']}")

    chain = transitive(slug)
    print(f"\nAll transitive prerequisites of '{slug}' ({len(chain)} total):\n")
    if not chain:
        print("  (none)")
    for r in chain:
        print(f"  depth={r['depth']}  {r['slug']:<40} {r['title']}")