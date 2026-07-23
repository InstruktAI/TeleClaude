"""Typed exceptions for inbound message guardrails."""

from __future__ import annotations

from typing import Literal

SessionMessageRejectionReason = Literal["not_found", "closed", "unavailable"]


class SessionMessageRejectedError(RuntimeError):
    """Permanent rejection when a session cannot accept inbound input."""

    def __init__(self, *, session_id: str, reason: SessionMessageRejectionReason) -> None:
        self.session_id = session_id
        self.reason = reason
        if reason == "not_found":
            message = f"Session {session_id} not found"
        elif reason == "unavailable":
            message = f"Session {session_id} is unavailable"
        else:
            message = f"Session {session_id} is closed"
        super().__init__(message)

    @property
    def http_status_code(self) -> int:
        if self.reason == "not_found":
            return 404
        return 409


class UnidentifiableCallerError(RuntimeError):
    """Raised when a session-originated send cannot be attributed a real-role identity header."""

    http_status_code = 409

    def __init__(self, *, caller_session_id: str) -> None:
        self.caller_session_id = caller_session_id
        super().__init__(
            f"Caller session {caller_session_id} has no resolvable machine role; "
            "refusing to deliver as unheadered (human-looking) input"
        )
