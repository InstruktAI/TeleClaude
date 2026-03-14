"""Characterization tests for teleclaude.core.error_feedback."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from teleclaude.core.error_feedback import get_user_facing_error_message
from teleclaude.core.events import ErrorEventContext


def _make_context(
    source: str = "",
    code: str = "",
    message: str | None = None,
    session_id: str | None = None,
) -> ErrorEventContext:
    ctx = MagicMock(spec=ErrorEventContext)
    ctx.source = source
    ctx.code = code
    ctx.message = message
    ctx.session_id = session_id
    return ctx


class TestGetUserFacingErrorMessage:
    @pytest.mark.unit
    def test_hook_invalid_json_returns_friendly_message(self):
        ctx = _make_context(source="hook_receiver", code="HOOK_INVALID_JSON")
        result = get_user_facing_error_message(ctx)
        assert result is not None
        assert "hook" in result.lower() or "json" in result.lower() or "telec" in result.lower()

    @pytest.mark.unit
    def test_hook_payload_not_object_returns_friendly_message(self):
        ctx = _make_context(source="hook_receiver", code="HOOK_PAYLOAD_NOT_OBJECT")
        result = get_user_facing_error_message(ctx)
        assert result is not None

    @pytest.mark.unit
    def test_hook_event_deprecated_returns_friendly_message(self):
        ctx = _make_context(source="hook_receiver", code="HOOK_EVENT_DEPRECATED")
        result = get_user_facing_error_message(ctx)
        assert result is not None

    @pytest.mark.unit
    def test_hook_receiver_unknown_code_with_message_returns_message(self):
        ctx = _make_context(source="hook_receiver", code="UNKNOWN_CODE", message="Something failed")
        result = get_user_facing_error_message(ctx)
        assert result is not None
        assert "Something failed" in result

    @pytest.mark.unit
    def test_hook_receiver_unknown_code_no_message_returns_generic(self):
        ctx = _make_context(source="hook_receiver", code="UNKNOWN_CODE", message=None)
        result = get_user_facing_error_message(ctx)
        assert result is not None

    @pytest.mark.unit
    def test_non_hook_source_returns_none(self):
        ctx = _make_context(source="internal_system", code="SOME_CODE")
        result = get_user_facing_error_message(ctx)
        assert result is None

    @pytest.mark.unit
    def test_empty_source_returns_none(self):
        ctx = _make_context(source="", code="HOOK_INVALID_JSON")
        result = get_user_facing_error_message(ctx)
        assert result is None
