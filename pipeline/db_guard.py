"""
Fail-closed write guard for pipeline database mutations.

The guard checks the resolved DSN against the known production Supabase project
ref, so a misleading PIPELINE_DB_TARGET label cannot wave a production write
through by itself.
"""
from __future__ import annotations

import argparse
import os
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from dotenv import load_dotenv


PROD_SUPABASE_REF = "dkqlxidjhydrlddryjxw"


class WriteGuardError(RuntimeError):
    """Raised when a DB write targets a disallowed or mismatched database."""


def _resolve_dsn() -> str:
    load_dotenv()
    dsn = os.environ.get("DIRECT_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        raise WriteGuardError(
            "No DIRECT_URL/DATABASE_URL set; refusing DB write (fail-closed)."
        )
    return dsn


def _project_ref(dsn: str) -> str | None:
    """
    Extract the Supabase project ref from common connection styles:
      postgresql://postgres:...@db.<ref>.supabase.co:5432/postgres
      postgresql://postgres.<ref>:...@...pooler.supabase.com:6543/postgres
      postgresql://postgres.<ref>:...@...pooler.supabase.com:5432/postgres
      https://<ref>.supabase.co
    """
    parsed = urlparse(dsn)
    host = (parsed.hostname or "").lower()
    user = (parsed.username or "").lower()

    if "." in user:
        candidate = user.split(".", 1)[1]
        if candidate:
            return candidate

    if host.endswith(".supabase.co") or host.endswith(".supabase.com"):
        labels = host.split(".")
        if labels[0] == "db" and len(labels) >= 4:
            return labels[1]
        if len(labels) >= 3 and labels[0] not in {"aws-0", "aws-1", "aws-2"}:
            return labels[0]
    return None


def ensure_writable(*, allow_prod: bool = False) -> None:
    """
    Refuse writes unless the target label agrees with the resolved DB ref.

    Non-prod writes require PIPELINE_DB_TARGET=dev and a DSN that does not
    resolve to PROD_SUPABASE_REF. Production writes require both
    PIPELINE_DB_TARGET=prod and PIPELINE_ALLOW_PROD_WRITES=1, or allow_prod=True.
    """
    target = os.environ.get("PIPELINE_DB_TARGET", "").strip().lower()
    if not target:
        raise WriteGuardError(
            "PIPELINE_DB_TARGET is unset; refusing DB write. "
            "Use PIPELINE_DB_TARGET=dev for non-prod or PIPELINE_DB_TARGET=prod "
            "with PIPELINE_ALLOW_PROD_WRITES=1 for an intentional production write."
        )

    ref = _project_ref(_resolve_dsn())
    is_prod_conn = ref == PROD_SUPABASE_REF

    if target == "dev":
        if is_prod_conn:
            raise WriteGuardError(
                "PIPELINE_DB_TARGET=dev but the connection resolves to the known "
                f"production ref ({ref}); refusing."
            )
        return

    if target == "prod":
        if not is_prod_conn:
            raise WriteGuardError(
                "PIPELINE_DB_TARGET=prod but the connection does not resolve to "
                f"the known production ref; got {ref or '(unknown)'}."
            )
        if allow_prod or os.environ.get("PIPELINE_ALLOW_PROD_WRITES") == "1":
            return
        raise WriteGuardError(
            "Refusing production write. Set PIPELINE_ALLOW_PROD_WRITES=1 for an "
            "intentional production operation."
        )

    raise WriteGuardError(
        f"Unrecognized PIPELINE_DB_TARGET={target!r}; use 'dev' or 'prod'."
    )


def _sanitize_dsn(dsn: str) -> str:
    parsed = urlparse(dsn)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    user = parsed.username or ""
    netloc = f"{user}:***@{host}{port}" if user else f"{host}{port}"
    query = urlencode(
        [
            (k, "***" if "password" in k.lower() or "token" in k.lower() else v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        ]
    )
    return urlunparse(
        (parsed.scheme, netloc, parsed.path, parsed.params, query, "")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Preflight pipeline DB writes.")
    parser.add_argument("--allow-prod", action="store_true")
    args = parser.parse_args()

    ensure_writable(allow_prod=args.allow_prod)
    dsn = _resolve_dsn()
    print(
        "DB write guard: OK "
        f"target={os.environ.get('PIPELINE_DB_TARGET')} "
        f"ref={_project_ref(dsn) or '(unknown)'} "
        f"dsn={_sanitize_dsn(dsn)}"
    )


if __name__ == "__main__":
    main()
