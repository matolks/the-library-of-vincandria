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

import hashlib
import os
import psycopg2
import json
from dotenv import load_dotenv
from dataclasses import dataclass
from pipeline.db_guard import ensure_writable

@dataclass
class ChunkRecord:
    content: str
    content_hash: str
    source_path: str
    source_type: str
    chunk_index: int
    page_number: int | None = None
    section_path: str | None = None
    token_count: int | None = None
    embedding: list[float] | None = None


def stable_chunk_id(course_id: str, chunk: ChunkRecord) -> str:
    """
    Deterministic chunk id for rerun-stable source_chunk_ids.

    The identity includes course, source location, and content hash. Rechunking
    the same artifact into the same content at the same slot yields the same id
    even after deleting/reseeding rows; changed content yields a new id.
    """
    payload = json.dumps(
        {
            "course_id": course_id,
            "source_path": chunk.source_path,
            "chunk_index": chunk.chunk_index,
            "content_hash": chunk.content_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "chunk_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

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
    ensure_writable()
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
    ensure_writable()
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
    ensure_writable()
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
# Reset (--reset flag in ingest.py)
# ---------------------------------------------------------------------------

def reset_course(course_id: str) -> None:
    """
    Delete all non-manually-edited blocks for every topic in a course.
    Topics and their group connections are preserved.
    """
    ensure_writable()
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


def get_course_id_or_raise(slug: str) -> str:
    course_id = get_course_id(slug)
    if course_id is None:
        raise ValueError(f"Course not found: {slug}")
    return course_id


def get_pipeline_state(
    course_id: str,
    stage: str,
    subject_key: str = "course",
) -> dict | None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            '''
            SELECT fingerprint, status, metadata, "updatedAt"
            FROM "PipelineState"
            WHERE "courseId" = %s AND stage = %s AND "subjectKey" = %s
            ''',
            (course_id, stage, subject_key),
        )
        row = cur.fetchone()
    if row is None:
        return None
    metadata = row[2] if isinstance(row[2], dict) else (json.loads(row[2]) if row[2] else None)
    return {
        "fingerprint": row[0],
        "status": row[1],
        "metadata": metadata,
        "updatedAt": row[3],
    }


def pipeline_state_matches(
    course_id: str,
    stage: str,
    subject_key: str,
    fingerprint: str,
    *,
    ok_statuses: set[str] | None = None,
) -> bool:
    state = get_pipeline_state(course_id, stage, subject_key)
    if state is None:
        return False
    ok_statuses = ok_statuses or {"ok"}
    return (
        state["fingerprint"] == fingerprint
        and state["status"] in ok_statuses
    )


def upsert_pipeline_state(
    course_id: str,
    stage: str,
    subject_key: str,
    fingerprint: str,
    status: str,
    metadata: dict | None = None,
) -> None:
    ensure_writable()
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            '''
            INSERT INTO "PipelineState" (
                id, "courseId", stage, "subjectKey", fingerprint, status,
                metadata, "createdAt", "updatedAt"
            )
            VALUES (
                gen_random_uuid()::text, %s, %s, %s, %s, %s, %s::jsonb,
                now(), now()
            )
            ON CONFLICT ("courseId", stage, "subjectKey") DO UPDATE SET
                fingerprint = EXCLUDED.fingerprint,
                status = EXCLUDED.status,
                metadata = EXCLUDED.metadata,
                "updatedAt" = now()
            ''',
            (
                course_id,
                stage,
                subject_key,
                fingerprint,
                status,
                json.dumps(metadata) if metadata is not None else None,
            ),
        )
    conn.commit()


def get_topic_group_id(slug: str) -> str | None:
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute('SELECT id FROM "TopicGroup" WHERE slug = %s', (slug,))
        row = cur.fetchone()
    return row[0] if row else None


def set_topic_embedding(topic_id: str, vec: list[float]) -> None:
    ensure_writable()
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
    ensure_writable()
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
    ensure_writable()
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
    

def upsert_chunks(course_id: str, chunks: list[ChunkRecord]) -> int:
    """
    Bulk upsert chunks by (courseId, sourcePath, chunkIndex).

    Chunk ids are deterministic and content-addressed enough for Agent 3
    provenance stability: same course/source/index/contentHash produces the
    same id across clean reseeds, while changed content at the same slot updates
    the row to a new id.

    Returns count written.
    """
    if not chunks:
        return 0

    ensure_writable()
    from psycopg2.extras import execute_values

    rows = [
        (
            stable_chunk_id(course_id, c),
            c.content,
            c.content_hash,
            c.source_path,
            c.source_type,
            c.chunk_index,
            c.page_number,
            c.section_path,
            c.token_count,
            c.embedding,
            course_id,
        )
        for c in chunks
    ]

    conn = get_conn()
    with conn.cursor() as cur:
        execute_values(
            cur,
            '''
            INSERT INTO "Chunk" (
                id, content, "contentHash", "sourcePath", "sourceType",
                "chunkIndex", "pageNumber", "sectionPath", "tokenCount",
                embedding, "courseId", "createdAt", "updatedAt"
            )
            VALUES %s
            ON CONFLICT ("courseId", "sourcePath", "chunkIndex") DO UPDATE SET
                id            = EXCLUDED.id,
                content       = EXCLUDED.content,
                "contentHash" = EXCLUDED."contentHash",
                "sourceType"  = EXCLUDED."sourceType",
                "pageNumber"  = EXCLUDED."pageNumber",
                "sectionPath" = EXCLUDED."sectionPath",
                "tokenCount"  = EXCLUDED."tokenCount",
                embedding     = EXCLUDED.embedding,
                "updatedAt"   = now()
            ''',
            rows,
            template='(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::vector, %s, now(), now())',
        )
    conn.commit()
    return len(chunks)


def delete_orphan_chunks(course_id: str, touched_keys: set[tuple[str, int]]) -> int:
    """
    Delete chunks for this course whose (sourcePath, chunkIndex) is not in touched_keys.
    Returns count deleted.
    """
    ensure_writable()
    conn = get_conn()
    with conn.cursor() as cur:
        if not touched_keys:
            cur.execute('DELETE FROM "Chunk" WHERE "courseId" = %s', (course_id,))
            deleted = cur.rowcount
        else:
            paths = [sp for sp, _ in touched_keys]
            indices = [ci for _, ci in touched_keys]
            cur.execute(
                '''
                DELETE FROM "Chunk"
                WHERE "courseId" = %s
                  AND ("sourcePath", "chunkIndex") NOT IN (
                    SELECT * FROM unnest(%s::text[], %s::int[])
                  )
                ''',
                (course_id, paths, indices),
            )
            deleted = cur.rowcount
    conn.commit()
    return deleted


def top_chunks_for_topic(topic_id: str, k: int = 8) -> list[dict]:
    """
    pgvector ANN retrieval: top-k chunks in the topic's course, ranked by cosine
    similarity against the topic's embedding. Uses the HNSW index via <=>.
    """
    conn = get_conn()
    with conn.cursor() as cur:
        cur.execute(
            'SELECT embedding, "courseId" FROM "Topic" WHERE id = %s',
            (topic_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Topic {topic_id} not found")
        if row[0] is None:
            raise ValueError(f"Topic {topic_id} has no embedding")
        target_emb, course_id = row

        cur.execute(
            '''
            SELECT
                id,
                content,
                "contentHash",
                "sourcePath",
                "sourceType",
                "pageNumber",
                "sectionPath",
                embedding <=> %s::vector AS distance
            FROM "Chunk"
            WHERE "courseId" = %s AND embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            ''',
            (target_emb, course_id, target_emb, k),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]



def replace_topic_blocks(
    topic_id: str,
    pinned_ids: list[str],
    sequence: list[dict],
) -> dict:
    """
    Atomically replace this topic's blocks with the given ordered sequence.

    Implements §6 step 4 of AGENT3_DESIGN.md. Single transaction; the
    (topicId, order) unique index is upheld throughout via a negative-order
    stash so anchors and new blocks can be repositioned without collisions.

    Args:
        topic_id: target topic.
        pinned_ids: the expanded pinned set computed at read time (§4 atomic
            rule). Every id here MUST appear as an anchor reference in
            `sequence`, otherwise the function refuses without touching the DB.
            This is the safety boundary against silently deleting user edits.
        sequence: ordered list emitted by the model. Each item is either:
            - Anchor reference: {"id": str}. The id must be in pinned_ids and
              must exist on the topic. Anchor content is NOT updated here;
              the anchor-integrity validator at the prompt layer guarantees the
              model returned the existing id with byte-identical content.
            - New block: {"type": str, "content": dict, "group_id"?: str|None,
              "generation_metadata"?: dict|None}. No id field; a fresh uuid is
              assigned at insert.

    Returns:
        {"pinned_kept": int, "new_inserted": int, "deleted": int}

    Raises:
        ValueError on any anchor/pinned mismatch or unknown anchor id.
        psycopg2 errors propagate after the transaction is rolled back.
    """
    ensure_writable()
    pinned_set = set(pinned_ids)
    anchor_refs = [item["id"] for item in sequence if "id" in item]
    anchor_set = set(anchor_refs)

    # --- Pre-DB validation: refuse before opening any cursor ---

    if pinned_set != anchor_set:
        missing = sorted(pinned_set - anchor_set)
        extra = sorted(anchor_set - pinned_set)
        parts = []
        if missing:
            parts.append(f"pinned blocks missing from sequence: {missing}")
        if extra:
            parts.append(f"sequence references non-pinned ids: {extra}")
        raise ValueError("; ".join(parts))

    if len(anchor_refs) != len(anchor_set):
        from collections import Counter
        dupes = sorted(k for k, v in Counter(anchor_refs).items() if v > 1)
        raise ValueError(f"sequence contains duplicate anchor refs: {dupes}")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # Defense in depth: verify every pinned id is actually on this topic.
            if pinned_set:
                cur.execute(
                    'SELECT id FROM "Block" WHERE "topicId" = %s AND id = ANY(%s)',
                    (topic_id, list(pinned_set)),
                )
                present = {r[0] for r in cur.fetchall()}
                missing_in_db = sorted(pinned_set - present)
                if missing_in_db:
                    raise ValueError(
                        f"pinned ids not present on topic {topic_id}: {missing_in_db}"
                    )

            # Step 1: stash all current orders into a negative range so the
            # unique index doesn't collide while we rewrite positions.
            cur.execute(
                'UPDATE "Block" SET "order" = -"order" - 1 WHERE "topicId" = %s',
                (topic_id,),
            )

            # Step 2: delete every block on this topic that isn't pinned.
            if pinned_set:
                cur.execute(
                    'DELETE FROM "Block" WHERE "topicId" = %s AND id <> ALL(%s)',
                    (topic_id, list(pinned_set)),
                )
            else:
                cur.execute(
                    'DELETE FROM "Block" WHERE "topicId" = %s',
                    (topic_id,),
                )
            deleted = cur.rowcount

            # Step 3: walk the sequence, dense order starting at 0.
            pinned_kept = 0
            new_inserted = 0
            for new_order, item in enumerate(sequence):
                if "id" in item:
                    cur.execute(
                        """
                        UPDATE "Block"
                        SET "order" = %s, "updatedAt" = now()
                        WHERE id = %s AND "topicId" = %s
                        """,
                        (new_order, item["id"], topic_id),
                    )
                    if cur.rowcount != 1:
                        raise ValueError(
                            f"anchor {item['id']!r} update affected "
                            f"{cur.rowcount} rows; expected 1"
                        )
                    pinned_kept += 1
                else:
                    cur.execute(
                        """
                        INSERT INTO "Block" (
                            id, type, content, "order", source, manually_edited,
                            generation_metadata, group_id, "topicId",
                            "createdAt", "updatedAt"
                        )
                        VALUES (
                            gen_random_uuid()::text, %s, %s::jsonb, %s,
                            'generated', false, %s::jsonb, %s, %s,
                            now(), now()
                        )
                        """,
                        (
                            item["type"],
                            json.dumps(item["content"]),
                            new_order,
                            json.dumps(item["generation_metadata"])
                                if item.get("generation_metadata") is not None
                                else None,
                            item.get("group_id"),
                            topic_id,
                        ),
                    )
                    new_inserted += 1

        conn.commit()
        return {
            "pinned_kept": pinned_kept,
            "new_inserted": new_inserted,
            "deleted": deleted,
        }

    except Exception:
        conn.rollback()
        raise
    
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
