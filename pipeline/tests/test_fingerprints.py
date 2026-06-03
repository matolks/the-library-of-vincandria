from __future__ import annotations

from dataclasses import replace

from pipeline import block_gen as bg
from pipeline.block_gen import (
    BlockCohort,
    ChunkContext,
    ExistingBlock,
    PrereqTopic,
    TopicContext,
    TopicRow,
    agent3_generation_config,
    compute_context_fingerprint,
)
from pipeline.fingerprints import fingerprint_payload
from pipeline.judge import compute_judge_fingerprint


def test_fingerprint_payload_is_key_order_independent():
    assert fingerprint_payload({"b": 2, "a": 1}) == fingerprint_payload(
        {"a": 1, "b": 2}
    )


def test_context_fingerprint_changes_when_chunk_hash_changes():
    base = _context(chunk_hash="hash_a")
    changed = _context(chunk_hash="hash_b")

    assert compute_context_fingerprint(base) != compute_context_fingerprint(changed)


def test_context_fingerprint_ignores_unpinned_existing_blocks():
    a = _context(unpinned_text="old generated text")
    b = _context(unpinned_text="new generated text")

    assert compute_context_fingerprint(a) == compute_context_fingerprint(b)


def test_context_fingerprint_changes_when_model_changes_without_prompt_bump():
    context = _context()
    sonnet = agent3_generation_config(model="claude-sonnet-4-6")
    opus = agent3_generation_config(model="claude-opus-4-7")

    assert compute_context_fingerprint(
        context,
        generation_config=sonnet,
    ) != compute_context_fingerprint(
        context,
        generation_config=opus,
    )


def test_context_fingerprint_changes_when_decoding_params_change():
    context = _context()
    temp_zero = agent3_generation_config(temperature=0)
    temp_one = agent3_generation_config(temperature=1)

    assert compute_context_fingerprint(
        context,
        generation_config=temp_zero,
    ) != compute_context_fingerprint(
        context,
        generation_config=temp_one,
    )


def test_context_fingerprint_changes_when_structured_json_mode_changes():
    context = _context()
    structured = agent3_generation_config(structured_json=True)
    prompt_only = agent3_generation_config(structured_json=False)

    assert compute_context_fingerprint(
        context,
        generation_config=structured,
    ) != compute_context_fingerprint(
        context,
        generation_config=prompt_only,
    )


def test_stale_decision_matrix_for_same_source_changed_source_and_model_swap(
    monkeypatch,
):
    base_config = agent3_generation_config(model="claude-sonnet-4-6")
    base_context = _context_with_stored_fingerprint(base_config)

    monkeypatch.setattr(bg, "get_topic_context", lambda topic_id: base_context)

    same = bg.explain_topic_staleness(
        "topic_1",
        generation_config=base_config,
    )
    model_swap = bg.explain_topic_staleness(
        "topic_1",
        generation_config=agent3_generation_config(model="claude-opus-4-7"),
    )

    changed_source = replace(
        base_context,
        chunks=(
            replace(base_context.chunks[0], content_hash="changed_chunk_hash"),
        ),
    )
    monkeypatch.setattr(bg, "get_topic_context", lambda topic_id: changed_source)
    source_change = bg.explain_topic_staleness(
        "topic_1",
        generation_config=base_config,
    )

    assert same.stale is False
    assert same.reason == "fingerprint_match"
    assert model_swap.stale is True
    assert model_swap.reason == "fingerprint_mismatch"
    assert source_change.stale is True
    assert source_change.reason == "fingerprint_mismatch"


def test_judge_fingerprint_changes_with_block_content():
    old = [_block("b1", "old generated text", order=0)]
    new = [_block("b1", "new generated text", order=0)]

    assert compute_judge_fingerprint(old) != compute_judge_fingerprint(new)


def _context(
    *,
    chunk_hash: str = "hash_a",
    unpinned_text: str = "generated",
) -> TopicContext:
    pinned = _block("pinned_1", "manual anchor", order=0, manually_edited=True)
    unpinned = _block("generated_1", unpinned_text, order=1)
    return TopicContext(
        topic=TopicRow(
            id="topic_1",
            slug="topic-slug",
            title="Topic Title",
            summary="Topic summary",
            course_slug="course-slug",
        ),
        prereqs=(PrereqTopic(slug="prereq-a", title="Prereq", summary=None),),
        chunks=(
            ChunkContext(
                id="chunk_1",
                content="source chunk text",
                content_hash=chunk_hash,
                source_path="lecture.pdf",
                page_number=1,
                similarity=0.91,
            ),
        ),
        cohorts=(
            BlockCohort(group_id=None, blocks=(pinned,), pinned=True),
            BlockCohort(group_id=None, blocks=(unpinned,), pinned=False),
        ),
        coverage="dense",
        top_similarity=0.91,
    )


def _context_with_stored_fingerprint(generation_config: dict) -> TopicContext:
    context = _context()
    fingerprint = compute_context_fingerprint(
        context,
        generation_config=generation_config,
    )
    generated = replace(
        context.cohorts[1].blocks[0],
        generation_metadata={"context_fingerprint": fingerprint},
    )
    return replace(
        context,
        cohorts=(
            context.cohorts[0],
            replace(context.cohorts[1], blocks=(generated,)),
        ),
    )


def _block(
    block_id: str,
    text: str,
    *,
    order: int,
    manually_edited: bool = False,
) -> ExistingBlock:
    return ExistingBlock(
        id=block_id,
        order=order,
        type="paragraph",
        content={
            "type": "paragraph",
            "content": [{"type": "text", "text": text}],
        },
        group_id=None,
        manually_edited=manually_edited,
        generation_metadata=None,
    )
