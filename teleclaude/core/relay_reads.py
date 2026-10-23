"""Existing caller-read vocabulary, shared without importing its execution handlers."""

from enum import StrEnum


class RelayRead(StrEnum):
    """Closed set of caller-facing reads executed by the computer that owns the data."""

    SESSION_MESSAGES = "get_session_messages"
    SESSION_PANE = "get_session_pane"
    OPERATION = "get_operation"
    SESSIONS = "list_sessions"
    SESSION_RECORD = "get_session_record"
