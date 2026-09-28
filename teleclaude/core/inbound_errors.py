"""Typed exceptions for inbound message guardrails."""

from __future__ import annotations

from enum import StrEnum


class SessionMessageRejectionReason(StrEnum):
    """Closed reasons for rejecting inbound session messages."""

    NOT_FOUND = "not_found"
    CLOSED = "closed"
    UNAVAILABLE = "unavailable"
    CALLER_IDENTITY_COMPATIBILITY = "caller_identity_compatibility"
    ADMISSION_REFUSED = "admission_refused"
    PEER_OCCURRENCE_REQUIRED = "peer_occurrence_required"


class SessionMessageRejectedError(RuntimeError):
    """Permanent rejection when a session cannot accept inbound input."""

    def __init__(
        self,
        *,
        session_id: str,
        reason: SessionMessageRejectionReason,
        detail: str | None = None,
    ) -> None:
        self.session_id = session_id
        self.reason = reason
        self.detail = detail
        if reason is SessionMessageRejectionReason.NOT_FOUND:
            message = f"Session {session_id} not found"
        elif reason is SessionMessageRejectionReason.UNAVAILABLE:
            message = f"Session {session_id} is unavailable"
        elif reason is SessionMessageRejectionReason.CALLER_IDENTITY_COMPATIBILITY:
            message = f"Session {session_id} received caller identity content that cannot be safely canonicalized"
        elif reason is SessionMessageRejectionReason.ADMISSION_REFUSED:
            message = detail or f"Session {session_id} rejected the input"
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


class DirectLinkExclusivityError(RuntimeError):
    """Raised when a direct link would give an endpoint a second concurrent peer.

    Direct conversation is exclusive to two sessions. The endpoint already in a
    conversation and the peer holding it are carried so the refusing surface can
    name that peer instead of reporting an anonymous conflict.
    """

    http_status_code = 409

    def __init__(
        self,
        *,
        endpoint_session_id: str,
        peer_session_id: str,
        peer_name: str | None,
        link_id: str,
    ) -> None:
        self.endpoint_session_id = endpoint_session_id
        self.peer_session_id = peer_session_id
        self.peer_name = peer_name
        self.link_id = link_id
        super().__init__(
            f"Session {endpoint_session_id} is already in a direct conversation "
            f"with {peer_name or peer_session_id} ({peer_session_id})"
        )
