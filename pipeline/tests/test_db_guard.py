from __future__ import annotations

import pytest

from pipeline import db_guard
from pipeline.db_guard import WriteGuardError, ensure_writable


POOL = "postgresql://postgres.{ref}:pw@aws-0-x.pooler.supabase.com:6543/postgres"
DIRECT = "postgresql://postgres:pw@db.{ref}.supabase.co:5432/postgres"
PROD = POOL.format(ref=db_guard.PROD_SUPABASE_REF)
DEV = POOL.format(ref="devref00000000000000")


@pytest.mark.parametrize(
    "target,dsn,allow,ok",
    [
        ("", DEV, None, False),
        ("dev", DEV, None, True),
        ("dev", PROD, None, False),
        ("prod", PROD, None, False),
        ("prod", PROD, "1", True),
        ("prod", DEV, "1", False),
        ("staging", DEV, None, False),
    ],
)
def test_guard(monkeypatch, target, dsn, allow, ok):
    monkeypatch.setenv("PIPELINE_DB_TARGET", target)
    monkeypatch.setenv("DIRECT_URL", dsn)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    if allow:
        monkeypatch.setenv("PIPELINE_ALLOW_PROD_WRITES", allow)
    else:
        monkeypatch.delenv("PIPELINE_ALLOW_PROD_WRITES", raising=False)

    if ok:
        ensure_writable()
    else:
        with pytest.raises(WriteGuardError):
            ensure_writable()


def test_project_ref_from_direct_supabase_host():
    dsn = DIRECT.format(ref=db_guard.PROD_SUPABASE_REF)

    assert db_guard._project_ref(dsn) == db_guard.PROD_SUPABASE_REF


def test_sanitize_dsn_masks_password():
    sanitized = db_guard._sanitize_dsn(PROD)

    assert "pw" not in sanitized
    assert ":***@" in sanitized
