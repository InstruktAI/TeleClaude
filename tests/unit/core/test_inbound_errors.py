"""Characterization tests for teleclaude.core.inbound_errors."""

from __future__ import annotations

import pytest

from teleclaude.core.inbound_errors import SessionMessageRejectedError


class TestSessionMessageRejectedError:
    @pytest.mark.unit
    def test_not_found_reason_sets_404_status(self):
        err = SessionMessageRejectedError(session_id="sess-001", reason="not_found")
        assert err.http_status_code == 404

    @pytest.mark.unit
    def test_closed_reason_sets_409_status(self):
        err = SessionMessageRejectedError(session_id="sess-001", reason="closed")
        assert err.http_status_code == 409

    @pytest.mark.unit
    def test_unavailable_reason_sets_409_status(self):
        err = SessionMessageRejectedError(session_id="sess-001", reason="unavailable")
        assert err.http_status_code == 409

    @pytest.mark.unit
    def test_stores_session_id(self):
        err = SessionMessageRejectedError(session_id="my-session", reason="not_found")
        assert err.session_id == "my-session"

    @pytest.mark.unit
    def test_stores_reason(self):
        err = SessionMessageRejectedError(session_id="sess", reason="closed")
        assert err.reason == "closed"

    @pytest.mark.unit
    def test_is_runtime_error_subclass(self):
        err = SessionMessageRejectedError(session_id="sess", reason="not_found")
        assert isinstance(err, RuntimeError)

    @pytest.mark.unit
    def test_message_includes_session_id(self):
        err = SessionMessageRejectedError(session_id="abc-123", reason="not_found")
        assert "abc-123" in str(err)
