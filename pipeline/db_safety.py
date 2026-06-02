"""
Database target safety checks for irreversible-ish pipeline rollout steps.

The migration and first full rerun write durable state. This module gives
operators a small, scriptable preflight before running those commands.
"""
from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from dotenv import load_dotenv


SAFE_TARGET_MARKERS = frozenset({"scratch", "dev", "development", "test", "local"})
UNSAFE_TARGET_MARKERS = frozenset({"prod", "production", "live"})


class DatabaseSafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatabaseTarget:
    env_var: str
    raw_url: str
    sanitized_url: str
    host: str
    database: str
    user: str
    explicit_label: str | None
    safe: bool
    reason: str


def inspect_database_target(
    *,
    env_var: str = "DIRECT_URL",
    explicit_label_var: str = "PIPELINE_DB_TARGET",
) -> DatabaseTarget:
    load_dotenv()
    raw_url = os.getenv(env_var) or ""
    if not raw_url:
        raise DatabaseSafetyError(f"{env_var} is not set")

    parsed = urlparse(raw_url)
    label = (os.getenv(explicit_label_var) or "").strip().lower() or None
    host = (parsed.hostname or "").lower()
    database = parsed.path.lstrip("/")
    user = parsed.username or ""

    unsafe_values = [v for v in (label, host, database, user) if _has_unsafe_marker(v)]
    if unsafe_values:
        safe = False
        reason = "unsafe_marker_present"
    elif label:
        safe = label in SAFE_TARGET_MARKERS
        reason = "explicit_label_safe" if safe else "explicit_label_not_safe"
    else:
        safe = any(_has_safe_marker(v) for v in (host, database, user))
        reason = "url_marker_safe" if safe else "no_safe_marker"

    return DatabaseTarget(
        env_var=env_var,
        raw_url=raw_url,
        sanitized_url=_sanitize_url(raw_url),
        host=host,
        database=database,
        user=user,
        explicit_label=label,
        safe=safe,
        reason=reason,
    )


def assert_scratch_or_dev(target: DatabaseTarget) -> None:
    if not target.safe:
        raise DatabaseSafetyError(
            "Refusing DB write preflight: target is not proven scratch/dev/test/local "
            f"({target.reason}; {target.sanitized_url}). Set PIPELINE_DB_TARGET=dev "
            "only after verifying the target is non-production."
        )


def _has_safe_marker(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.lower()
    return any(marker in normalized for marker in SAFE_TARGET_MARKERS)


def _has_unsafe_marker(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.lower()
    return any(marker in normalized for marker in UNSAFE_TARGET_MARKERS)


def _sanitize_url(raw_url: str) -> str:
    parsed = urlparse(raw_url)
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    user = parsed.username or ""
    netloc = f"{user}:***@{host}{port}" if user else f"{host}{port}"
    safe_query = urlencode(
        [
            (key, "***" if "password" in key.lower() or "token" in key.lower() else value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        ]
    )
    return urlunparse(
        (
            parsed.scheme,
            netloc,
            parsed.path,
            parsed.params,
            safe_query,
            "",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Check pipeline DB target safety.")
    parser.add_argument("--env-var", default="DIRECT_URL")
    parser.add_argument("--require-scratch-dev", action="store_true")
    args = parser.parse_args()

    target = inspect_database_target(env_var=args.env_var)
    if args.require_scratch_dev:
        assert_scratch_or_dev(target)
    status = "safe" if target.safe else "unsafe"
    print(
        f"{status}: env={target.env_var} target={target.sanitized_url} "
        f"reason={target.reason} label={target.explicit_label or '(none)'}"
    )


if __name__ == "__main__":
    main()
