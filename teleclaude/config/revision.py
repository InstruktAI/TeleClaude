"""Opaque revision digests for configuration subject views.

A revision is a stable digest of a subject's writable sections, used for
optimistic-concurrency refusal (RFC 9110 §13.1.1 `ETag`/`If-Match` pattern): a
caller reads a subject, computes or receives its revision, and a later patch
against a stale revision is refused before any candidate document is built.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

_REVISION_TAG = "v1"


class StaleRevision(ValueError):
    """A patch's expected revision no longer matches the subject's current one."""

    def __init__(self, expected: str, actual: str) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"Stale revision: expected {expected!r}, subject is now at {actual!r}")


def view_revision(sections: Mapping[str, object]) -> str:
    """Return an opaque, content-stable digest of a subject's writable sections."""
    canonical = json.dumps(sections, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{_REVISION_TAG}:{digest}"
