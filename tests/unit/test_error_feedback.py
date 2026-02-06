"""Tests for user-facing error message filtering."""

from teleclaude.core.error_feedback import get_user_facing_error_message
from teleclaude.core.events import ErrorEventContext


def test_hook_receiver_invalid_json_is_user_facing() -> None:
    context = ErrorEventContext(
        session_id="s1",
        message="Invalid hook payload JSON from stdin",
        source="hook_receiver",
        code="HOOK_INVALID_JSON",
    )
    message = get_user_facing_error_message(context)
    assert message is not None
    assert "telec init" in message


def test_hook_receiver_unknown_code_falls_back_to_generic() -> None:
    context = ErrorEventContext(
        session_id="s1",
        message="Unexpected hook parse failure",
        source="hook_receiver",
        code="HOOK_SOMETHING_NEW",
    )
    assert get_user_facing_error_message(context) == "Hook error: Unexpected hook parse failure"


def test_non_hook_errors_are_suppressed() -> None:
    context = ErrorEventContext(
        session_id="s1",
        message="database is locked",
        source="teleclaude.core.event_guard._guarded",
        code="INTERNAL",
    )
    assert get_user_facing_error_message(context) is None
