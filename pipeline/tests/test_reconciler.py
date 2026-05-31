"""
pipeline/tests/test_reconciler.py

Fixture-driven tests for db.replace_topic_blocks.

Each test:
  1. Creates a throwaway Course + Topic.
  2. Inserts setup.blocks verbatim (explicit ids).
  3. Calls db.replace_topic_blocks(topic_id, pinned_ids, sequence).
  4. Asserts either success (block_count, anchors, new orders, content
     preservation, dense ordering) or error (type, message substring, DB
     unchanged).
  5. Drops the topic+course in teardown.

Run:
  pytest pipeline/tests/test_reconciler.py -v
"""
from __future__ import annotations

import json
import pathlib
import uuid

import pytest

from pipeline import db


FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures" / "reconciler"


def _all_fixtures() -> list[pathlib.Path]:
    return sorted(FIXTURE_DIR.glob("case_*.json"))


@pytest.fixture
def synthetic_topic():
    """Create a throwaway course+topic, yield (course_id, topic_id), drop after."""
    conn = db.get_conn()
    course_id = f"crs_test_{uuid.uuid4().hex[:8]}"
    topic_id = f"tpc_test_{uuid.uuid4().hex[:8]}"
    course_slug = f"test-{uuid.uuid4().hex[:8]}"
    topic_slug = f"test-topic-{uuid.uuid4().hex[:8]}"
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO "Course" (id, slug, name, "createdAt", "updatedAt")
            VALUES (%s, %s, %s, now(), now())
            """,
            (course_id, course_slug, "test course"),
        )
        cur.execute(
            """
            INSERT INTO "Topic" (id, slug, title, summary, "order", "courseId",
                                 "createdAt", "updatedAt")
            VALUES (%s, %s, %s, %s, %s, %s, now(), now())
            """,
            (topic_id, topic_slug, "test topic", "for fixtures", 0, course_id),
        )
    conn.commit()
    try:
        yield (course_id, topic_id)
    finally:
        with conn.cursor() as cur:
            cur.execute('DELETE FROM "Block" WHERE "topicId" = %s', (topic_id,))
            cur.execute('DELETE FROM "Topic" WHERE id = %s', (topic_id,))
            cur.execute('DELETE FROM "Course" WHERE id = %s', (course_id,))
        conn.commit()


def _insert_setup_blocks(topic_id: str, blocks: list[dict]) -> None:
    conn = db.get_conn()
    with conn.cursor() as cur:
        for b in blocks:
            cur.execute(
                """
                INSERT INTO "Block" (
                    id, type, content, "order", source, manually_edited,
                    generation_metadata, group_id, "topicId",
                    "createdAt", "updatedAt"
                )
                VALUES (
                    %s, %s, %s::jsonb, %s, 'generated', %s, %s::jsonb, %s, %s,
                    now(), now()
                )
                """,
                (
                    b["id"],
                    b["type"],
                    json.dumps(b["content"]),
                    b["order"],
                    b["manually_edited"],
                    json.dumps(b["generation_metadata"])
                        if b.get("generation_metadata") is not None
                        else None,
                    b.get("group_id"),
                    topic_id,
                ),
            )
    conn.commit()


def _fetch_blocks(topic_id: str) -> list[dict]:
    conn = db.get_conn()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, type, content, "order", manually_edited, group_id, source
            FROM "Block"
            WHERE "topicId" = %s
            ORDER BY "order"
            """,
            (topic_id,),
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


@pytest.mark.parametrize(
    "fixture_path",
    _all_fixtures(),
    ids=lambda p: p.stem,
)
def test_reconciler(fixture_path: pathlib.Path, synthetic_topic):
    _, topic_id = synthetic_topic
    fixture = json.loads(fixture_path.read_text())

    setup_blocks = fixture["setup"]["blocks"]
    setup_ids = {b["id"] for b in setup_blocks}
    _insert_setup_blocks(topic_id, setup_blocks)

    pinned_ids = fixture["pinned_ids"]
    sequence = fixture["sequence"]
    expected = fixture["expected"]

    if expected["kind"] == "error":
        with pytest.raises(Exception) as exc_info:
            db.replace_topic_blocks(topic_id, pinned_ids, sequence)
        assert type(exc_info.value).__name__ == expected["error_type"]
        assert expected["message_contains"] in str(exc_info.value)
        # DB should be unchanged from setup
        after = _fetch_blocks(topic_id)
        assert len(after) == len(setup_blocks), \
            "error case left the DB modified — rollback failed"
        return

    # Success case
    result = db.replace_topic_blocks(topic_id, pinned_ids, sequence)
    after = _fetch_blocks(topic_id)

    # Block count
    assert len(after) == expected["block_count"], \
        f"expected {expected['block_count']} blocks, got {len(after)}"

    # Dense ordering 0..N-1
    orders = [b["order"] for b in after]
    assert orders == list(range(len(after))), f"orders not dense: {orders}"

    # Anchors preserved at expected slots with byte-identical content
    setup_by_id = {b["id"]: b for b in setup_blocks}
    after_by_order = {b["order"]: b for b in after}
    for anchor in expected["anchors_preserved"]:
        slot = after_by_order[anchor["order"]]
        assert slot["id"] == anchor["id"], \
            f"order {anchor['order']}: expected anchor {anchor['id']}, got {slot['id']}"
        original = setup_by_id[anchor["id"]]
        assert slot["content"] == original["content"], \
            f"anchor {anchor['id']}: content mutated"
        assert slot["manually_edited"] == original["manually_edited"]
        assert slot["group_id"] == original["group_id"]

    # New blocks at expected slots have fresh ids
    for order in expected["new_blocks_at_orders"]:
        slot = after_by_order[order]
        assert slot["id"] not in setup_ids, \
            f"order {order}: expected fresh uuid, got setup id {slot['id']}"
        # Cross-check type/content against the corresponding sequence item
        seq_item = sequence[order]
        assert "id" not in seq_item, \
            f"sequence[{order}] is an anchor; expected new block"
        assert slot["type"] == seq_item["type"]
        assert slot["content"] == seq_item["content"]

    # Counters from reconciler match the fixture's implied counts
    assert result["pinned_kept"] == len(expected["anchors_preserved"])
    assert result["new_inserted"] == len(expected["new_blocks_at_orders"])
    assert result["deleted"] == len(setup_blocks) - result["pinned_kept"]