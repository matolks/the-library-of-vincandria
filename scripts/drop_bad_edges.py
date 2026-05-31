# scripts/drop_bad_edges.py
from pipeline.db import get_conn

BAD_EDGES = [
    ("mvc-chain-rule", "mvc-vector-calculus-ops"),
    ("mvc-quadric-surfaces", "mvc-parametric-curves"),
    ("mvc-dot-product", "mvc-parametric-curves"),
    ("mvc-lines-planes-3d", "mvc-multivariable-functions"),
]

def main() -> None:
    with get_conn() as conn, conn.cursor() as cur:
        for from_slug, to_slug in BAD_EDGES:
            cur.execute(
                '''
                DELETE FROM "TopicEdge"
                WHERE "fromId" = (SELECT id FROM "Topic" WHERE slug = %s)
                  AND "toId"   = (SELECT id FROM "Topic" WHERE slug = %s)
                ''',
                (from_slug, to_slug),
            )
            print(f"deleted {from_slug} -> {to_slug}: {cur.rowcount} row")
        conn.commit()


if __name__ == "__main__":
    main()
