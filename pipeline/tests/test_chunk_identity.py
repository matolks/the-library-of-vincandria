from __future__ import annotations

from pipeline.db import ChunkRecord, stable_chunk_id


def test_stable_chunk_id_repeats_for_same_course_location_and_content_hash():
    chunk = _chunk(content_hash="hash_a")

    assert stable_chunk_id("course_1", chunk) == stable_chunk_id("course_1", chunk)


def test_stable_chunk_id_changes_when_content_hash_changes():
    old = _chunk(content_hash="hash_a")
    new = _chunk(content_hash="hash_b")

    assert stable_chunk_id("course_1", old) != stable_chunk_id("course_1", new)


def test_stable_chunk_id_changes_when_source_slot_changes():
    first = _chunk(chunk_index=0)
    second = _chunk(chunk_index=1)

    assert stable_chunk_id("course_1", first) != stable_chunk_id("course_1", second)


def _chunk(
    *,
    content_hash: str = "hash_a",
    chunk_index: int = 0,
) -> ChunkRecord:
    return ChunkRecord(
        content="source text",
        content_hash=content_hash,
        source_path="lecture.pdf",
        source_type="lectures",
        chunk_index=chunk_index,
        page_number=1,
        section_path=None,
        token_count=2,
        embedding=None,
    )
