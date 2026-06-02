"""
Deterministic fingerprints for pipeline change detection.

The helpers here intentionally accept ordinary Python data structures and
produce stable sha256 hex digests. Callers are responsible for choosing the
right semantic inputs for each stage.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def fingerprint_payload(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def versioned_fingerprint(version: str, value: Any) -> str:
    return fingerprint_payload({"version": version, "payload": value})
