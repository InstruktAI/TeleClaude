"""Closed vocabulary for the code-conformance return API and audit record."""

from __future__ import annotations

from enum import StrEnum


class TodoReturnToWorkApiRoute(StrEnum):
    """Public HTTP route used by the todo return command."""

    PATH = "/todos/return-to-work"
    ROUTER_PATH = "/return-to-work"


class TodoReturnToWorkRequestField(StrEnum):
    """Field names shared by the CLI payload and API request."""

    SLUG = "slug"
    REASON = "reason"
    EVIDENCE = "evidence"
    CWD = "cwd"


class TodoReturnToWorkResponseField(StrEnum):
    """Field names returned by the todo return API."""

    STATUS = "status"


class TodoReturnToWorkResultStatus(StrEnum):
    """Successful result emitted by the todo return API."""

    OK = "ok"


class TodoReturnToWorkAuditField(StrEnum):
    """Field names in the durable code-conformance return event."""

    REASON = "reason"
    EVIDENCE = "evidence"
    CANDIDATE_SHA = "candidate_sha"
    FROM_PHASE = "from_phase"


class TodoReturnToWorkGitRef(StrEnum):
    """Canonical refs checked before returning a candidate to work."""

    LOCAL_MAIN = "main"
    REMOTE_MAIN = "origin/main"


__all__ = [
    "TodoReturnToWorkApiRoute",
    "TodoReturnToWorkAuditField",
    "TodoReturnToWorkGitRef",
    "TodoReturnToWorkRequestField",
    "TodoReturnToWorkResponseField",
    "TodoReturnToWorkResultStatus",
]
