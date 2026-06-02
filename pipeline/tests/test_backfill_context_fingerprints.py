from __future__ import annotations

from dataclasses import replace

from pipeline import backfill_context_fingerprints as backfill
from pipeline.block_gen import agent3_generation_config, compute_context_fingerprint
from pipeline.tests.test_fingerprints import _context


def test_classify_topic_would_backfill_missing_context_fingerprints(monkeypatch):
    context = _context()
    monkeypatch.setattr(backfill, "get_topic_context", lambda topic_id: context)

    decision, block_ids = backfill.classify_topic(
        "topic_1",
        generation_config=agent3_generation_config(model="claude-sonnet-4-6"),
    )

    assert decision.status == "would_backfill"
    assert decision.reason == "missing_context_fingerprint"
    assert decision.blocks_to_update == 1
    assert block_ids == ("generated_1",)


def test_classify_topic_skips_when_current_fingerprint_exists(monkeypatch):
    config = agent3_generation_config(model="claude-sonnet-4-6")
    context = _context()
    fingerprint = compute_context_fingerprint(context, generation_config=config)
    generated = replace(
        context.cohorts[1].blocks[0],
        generation_metadata={"context_fingerprint": fingerprint},
    )
    context = replace(
        context,
        cohorts=(
            context.cohorts[0],
            replace(context.cohorts[1], blocks=(generated,)),
        ),
    )
    monkeypatch.setattr(backfill, "get_topic_context", lambda topic_id: context)

    decision, block_ids = backfill.classify_topic(
        "topic_1",
        generation_config=config,
    )

    assert decision.status == "skipped"
    assert decision.reason == "already_current"
    assert block_ids == ()


def test_classify_topic_requires_regeneration_on_mismatched_fingerprint(monkeypatch):
    context = _context()
    generated = replace(
        context.cohorts[1].blocks[0],
        generation_metadata={"context_fingerprint": "old-fingerprint"},
    )
    context = replace(
        context,
        cohorts=(
            context.cohorts[0],
            replace(context.cohorts[1], blocks=(generated,)),
        ),
    )
    monkeypatch.setattr(backfill, "get_topic_context", lambda topic_id: context)

    decision, block_ids = backfill.classify_topic(
        "topic_1",
        generation_config=agent3_generation_config(model="claude-sonnet-4-6"),
    )

    assert decision.status == "needs_regeneration"
    assert decision.reason == "stored_fingerprint_mismatch"
    assert block_ids == ()


def test_apply_backfill_merges_metadata_for_non_manual_blocks(monkeypatch):
    calls = []
    monkeypatch.setattr(backfill, "ensure_writable", lambda: None)

    class _Cursor:
        rowcount = 2

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, sql, params):
            calls.append((sql, params))

    class _Conn:
        def cursor(self):
            return _Cursor()

        def commit(self):
            calls.append(("commit", None))

    monkeypatch.setattr(backfill.db, "get_conn", lambda: _Conn())

    updated = backfill.apply_backfill(
        ["block_1", "block_2"],
        context_fingerprint="fp",
        backfilled_at="2026-06-01T00:00:00+00:00",
    )

    assert updated == 2
    sql, params = calls[0]
    assert "manually_edited = false" in sql
    assert "context_fingerprint" in params[0]
    assert params[1] == ["block_1", "block_2"]
    assert calls[1] == ("commit", None)
