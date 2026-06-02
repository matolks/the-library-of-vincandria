# scripts/drop_bad_edges.py
from pipeline.db import get_conn
from pipeline.db_guard import ensure_writable
from pipeline.mapper import MANUAL_EXCLUDED_EDGES

BAD_EDGES = sorted(MANUAL_EXCLUDED_EDGES)

def main() -> None:
    ensure_writable()
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
