"""Typed exceptions for inbound message guardrails."""

from __future__ import annotations

from typing import Literal

SessionMessageRejectionReason = Literal["not_found", "closed"]


class SessionMessageRejectedError(RuntimeError):
    """Permanent rejection when a session cannot accept inbound input."""

    def __init__(self, *, session_id: str, reason: SessionMessageRejectionReason) -> None:
        self.session_id = session_id
        self.reason = reason
        if reason == "not_found":
            message = f"Session {session_id[:8]} not found"
        else:
            message = f"Session {session_id[:8]} is closed"
        super().__init__(message)

    @property
    def http_status_code(self) -> int:
        if self.reason == "not_found":
            return 404
        return 409
