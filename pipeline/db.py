"""
pipeline/db.py

Supabase write client for the pipeline.
All writes go through psycopg2 directly -- no Prisma client in Python.
Prisma is Node-only; this module replicates the same upsert logic in raw SQL.

Idempotency rules:
- TopicGroup: upsert on slug
- Course: upsert on slug
- Topic: upsert on slug; updates title, summary, order, group connections
- Block: upsert on (topicId, order); skips any block where manually_edited = true

Connection is established once and reused. Call db.close() when done.
"""

import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DIRECT_URL")  # direct connection, not pooled
if not DATABASE_URL:
    raise EnvironmentError("DIRECT_URL is not set in .env")


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

_conn = None


def get_conn():
    global _conn
    if _conn is None or _conn.closed:
        _conn = psycopg2.connect(DATABASE_URL)
        _conn.autocommit = False
    return _conn


def close():
    global _conn
    if _conn and not _conn.closed:
        _conn.close()
        _conn = None


# ---------------------------------------------------------------------------
# TopicGroup
# ---------------------------------------------------------------------------

def upsert_topic_group(slug: str, name: str, description: str | None = None) -> str:
    """
    Upsert a TopicGroup by slug. Returns the id.
    """
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO "TopicGroup" (id, slug, name, description, "createdAt", "updatedAt")
            VALUES (gen_random_uuid()::text, %s, %s, %s, now(), now())
            ON CONFLICT (slug) DO UPDATE
                SET name        = EXCLUDED.name,
                    description = EXCLUDED.description,
                    "updatedAt" = now()
            RETURNING id
            """,
            (slug, name, description),
        )
        row = cur.fetchone()
    conn.commit()
    return row[0]


# ---------------------------------------------------------------------------
# Course
# ---------------------------------------------------------------------------

def upsert_course(slug: str, name: str) -> str:
    """
    Upsert a Course by slug. Returns the id.
    """
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO "Course" (id, slug, name, "createdAt", "updatedAt")
            VALUES (gen_random_uuid()::text, %s, %s, now(), now())
            ON CONFLICT (slug) DO UPDATE
                SET name       = EXCLUDED.name,
                    "updatedAt" = now()
            RETURNING id
            """,
            (slug, name),
        )
        row = cur.fetchone()
    conn.commit()
    return row[0]


# ---------------------------------------------------------------------------
# Topic
# ---------------------------------------------------------------------------

def upsert_topic(
    slug: str,
    title: str,
    summary: str | None,
    order: int,
    course_id: str,
    group_ids: list[str],
) -> str:
    """
    Upsert a Topic by slug. Replaces all group connections.
    Returns the topic id.
    """
    conn = get_conn()
    with conn.cursor() as cur:
        # Upsert topic row
        cur.execute(
            """
            INSERT INTO "Topic" (id, slug, title, summary, "order", "courseId", "createdAt", "updatedAt")
            VALUES (gen_random_uuid()::text, %s, %s, %s, %s, %s, now(), now())
            ON CONFLICT (slug) DO UPDATE
                SET title      = EXCLUDED.title,
                    summary    = EXCLUDED.summary,
                    "order"    = EXCLUDED."order",
                    "courseId" = EXCLUDED."courseId",
                    "updatedAt" = now()
            RETURNING id
            """,
            (slug, title, summary, order, course_id),
        )
        topic_id = cur.fetchone()[0]

        # Prisma implicit many-to-many join table _TopicGroups.
        # Columns: A = Topic.id, B = TopicGroup.id (alphabetical model order: Topic < TopicGroup).
        cur.execute(
            'DELETE FROM "_TopicGroups" WHERE "A" = %s',
            (topic_id,),
        )
        for group_id in group_ids:
            cur.execute(
                """
                INSERT INTO "_TopicGroups" ("A", "B")
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (topic_id, group_id),
            )
    conn.commit()
    return topic_id


# ---------------------------------------------------------------------------
# Block
# ---------------------------------------------------------------------------

def upsert_blocks(topic_id: str, blocks: list[dict]) -> int:
    """
    Upsert blocks for a topic. Skips any block where manually_edited = true.
    blocks: list of dicts with keys: type, content, order, language (optional)
    Returns count of blocks written.
    """
    conn = get_conn()
    written = 0

    with conn.cursor() as cur:
        for block in blocks:
            order = block["order"]

            # Check manually_edited flag before touching
            cur.execute(
                """
                SELECT manually_edited FROM "Block"
                WHERE "topicId" = %s AND "order" = %s
                """,
                (topic_id, order),
            )
            row = cur.fetchone()
            if row and row[0]:  # manually_edited = true
                continue

            cur.execute(
                """
                INSERT INTO "Block" (id, type, content, "order", language, source, citation, manually_edited, "topicId", "createdAt", "updatedAt")
                VALUES (gen_random_uuid()::text, %s, %s, %s, %s, %s, %s, false, %s, now(), now())
                ON CONFLICT ("topicId", "order") DO UPDATE
                    SET type       = EXCLUDED.type,
                        content    = EXCLUDED.content,
                        language   = EXCLUDED.language,
                        source     = EXCLUDED.source,
                        citation   = EXCLUDED.citation,
                        "updatedAt" = now()
                WHERE "Block".manually_edited = false
                """,
                (
                    block["type"],
                    block["content"],
                    order,
                    block.get("language"),
                    block.get("source", "generated"),
                    block.get("citation"),
                    topic_id,
                ),
            )
            written += 1

    conn.commit()
    return written


# ---------------------------------------------------------------------------
# Reset (--reset flag in ingest.py)
# ---------------------------------------------------------------------------

def reset_course(course_id: str) -> None:
    """
    Delete all non-manually-edited blocks for every topic in a course.
    Topics and their group connections are preserved.
    """
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM "Block"
            WHERE "topicId" IN (
                SELECT id FROM "Topic" WHERE "courseId" = %s
            )
            AND manually_edited = false
            """,
            (course_id,),
        )
        deleted = cur.rowcount
    conn.commit()
    print(
        f"Reset: deleted {deleted} blocks (manually_edited blocks preserved)")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def get_course_id(slug: str) -> str | None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute('SELECT id FROM "Course" WHERE slug = %s', (slug,))
        row = cur.fetchone()
    return row[0] if row else None


def get_topic_group_id(slug: str) -> str | None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute('SELECT id FROM "TopicGroup" WHERE slug = %s', (slug,))
        row = cur.fetchone()
    return row[0] if row else None


def set_topic_embedding(topic_id: str, vec: list[float]) -> None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            'UPDATE "Topic" SET embedding = %s::vector WHERE id = %s',
            (vec, topic_id),
        )
    conn.commit()

def set_topic_embeddings(pairs: list[tuple[str, list[float]]]) -> None:
    """
    Batch update embeddings for many topics in one round-trip.
    pairs: list of (topic_id, vector) tuples.
    """
    if not pairs:
        return
    from psycopg2.extras import execute_batch
    conn = get_conn()
    with conn.cursor() as cur:
        execute_batch(
            cur,
            'UPDATE "Topic" SET embedding = %s::vector WHERE id = %s',
            [(vec, tid) for tid, vec in pairs],
        )
    conn.commit()

def delete_orphan_topics(course_id: str, keep_slugs: list[str]) -> int:
    """
    Delete topics in a course whose slugs are not in keep_slugs.
    Cascades to TopicEdge and _TopicGroups.
    Returns count deleted.
    """
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            'DELETE FROM "Topic" WHERE "courseId" = %s AND slug != ALL(%s)',
            (course_id, keep_slugs),
        )
        deleted = cur.rowcount
    conn.commit()
    return deleted

def get_existing_topics_for_course(course_slug: str) -> list[dict]:
    """
    Return existing topics for a course as [{slug, title, summary}, ...].
    Used to anchor slug stability across re-runs.
    """
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT t.slug, t.title, t.summary
            FROM "Topic" t
            JOIN "Course" c ON c.id = t."courseId"
            WHERE c.slug = %s
            ORDER BY t."order"
            ''',
            (course_slug,),
        )
        rows = cur.fetchall()
    return [{"slug": r[0], "title": r[1], "summary": r[2]} for r in rows]

def nearest_topic_candidates(
    topic_id: str,
    k: int = 30,
    course_id: str | None = None,
) -> list[dict]:
    """
    Top-K nearest topics to `topic_id` by cosine distance on Topic.embedding.
    Excludes the target. Skips topics with NULL embeddings.
    If course_id is given, restricts to that course; else searches globally.
    Uses the HNSW index via the `<=>` (cosine) operator.
    """
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute('SELECT embedding FROM "Topic" WHERE id = %s', (topic_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Topic {topic_id} not found")
        if row[0] is None:
            raise ValueError(f"Topic {topic_id} has no embedding")
        target_emb = row[0]  # psycopg2 returns pgvector as string; round-trips fine

        cur.execute(
            """
            SELECT
                id,
                slug,
                title,
                summary,
                embedding <=> %s::vector AS distance
            FROM "Topic"
            WHERE id <> %s
              AND embedding IS NOT NULL
              AND (%s::text IS NULL OR "courseId" = %s)
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (target_emb, topic_id, course_id, course_id, target_emb, k),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
    
if __name__ == "__main__":
    import sys
    slug = sys.argv[1] if len(sys.argv) > 1 else "mvc-partial-derivatives"
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 10

    with get_conn() as conn, conn.cursor() as cur:
        cur.execute('SELECT id, "courseId" FROM "Topic" WHERE slug = %s', (slug,))
        row = cur.fetchone()
        if not row:
            print(f"no topic with slug={slug}")
            sys.exit(1)
        topic_id, course_id = row

    print(f"\nNearest {k} to '{slug}' (course-scoped):\n")
    for r in nearest_topic_candidates(topic_id, k=k, course_id=course_id):
        print(f"  {r['distance']:.4f}  {r['slug']:<40} {r['title']}")

    print(f"\nNearest {k} to '{slug}' (global):\n")
    for r in nearest_topic_candidates(topic_id, k=k, course_id=None):
        print(f"  {r['distance']:.4f}  {r['slug']:<40} {r['title']}")