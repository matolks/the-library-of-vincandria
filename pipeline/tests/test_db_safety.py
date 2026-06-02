from __future__ import annotations

import pytest

from pipeline.db_safety import (
    DatabaseSafetyError,
    assert_scratch_or_dev,
    inspect_database_target,
)


def test_explicit_dev_label_marks_target_safe(monkeypatch):
    monkeypatch.setenv("DIRECT_URL", "postgresql://user:secret@db.example.com/app")
    monkeypatch.setenv("PIPELINE_DB_TARGET", "dev")

    target = inspect_database_target()

    assert target.safe is True
    assert target.reason == "explicit_label_safe"
    assert target.explicit_label == "dev"


def test_production_marker_overrides_safe_label(monkeypatch):
    monkeypatch.setenv("DIRECT_URL", "postgresql://user:secret@prod.example.com/app")
    monkeypatch.setenv("PIPELINE_DB_TARGET", "dev")

    target = inspect_database_target()

    assert target.safe is False
    assert target.reason == "unsafe_marker_present"
    with pytest.raises(DatabaseSafetyError, match="Refusing DB write preflight"):
        assert_scratch_or_dev(target)


def test_url_dev_marker_marks_target_safe_without_label(monkeypatch):
    monkeypatch.setenv("DIRECT_URL", "postgresql://user:secret@dev-db.example.com/app")
    monkeypatch.delenv("PIPELINE_DB_TARGET", raising=False)

    target = inspect_database_target()

    assert target.safe is True
    assert target.reason == "url_marker_safe"


def test_sanitized_url_masks_password(monkeypatch):
    monkeypatch.setenv(
        "DIRECT_URL",
        "postgresql://user:secret@dev-db.example.com/app?sslmode=require",
    )
    monkeypatch.delenv("PIPELINE_DB_TARGET", raising=False)

    target = inspect_database_target()

    assert "secret" not in target.sanitized_url
    assert "user:***@dev-db.example.com" in target.sanitized_url
