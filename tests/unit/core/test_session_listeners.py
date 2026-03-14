"""Characterization tests for teleclaude.core.session_listeners."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from teleclaude.core.session_listeners import ConversationLink, SessionListener


class TestSessionListener:
    # SessionListener is a plain dataclass with no computed properties or
    # validation. Field storage is the public contract; these tests pin it.
    @pytest.mark.unit
    def test_stores_required_fields(self):
        now = datetime.now(UTC)
        listener = SessionListener(
            target_session_id="target-001",
            caller_session_id="caller-001",
            caller_tmux_session="tc-caller-001",
            registered_at=now,
        )
        assert listener.target_session_id == "target-001"
        assert listener.caller_session_id == "caller-001"
        assert listener.caller_tmux_session == "tc-caller-001"
        assert listener.registered_at == now


class TestConversationLink:
    @pytest.mark.unit
    def test_stores_required_fields(self):
        now = datetime.now(UTC)
        link = ConversationLink(
            link_id="link-001",
            mode="bidirectional",
            status="active",
            created_by_session_id="sess-001",
            created_at=now,
            updated_at=now,
            closed_at=None,
            metadata=None,
        )
        assert link.link_id == "link-001"
        assert link.mode == "bidirectional"
        assert link.status == "active"
        assert link.closed_at is None

    @pytest.mark.unit
    def test_closed_at_can_be_set(self):
        now = datetime.now(UTC)
        link = ConversationLink(
            link_id="link-001",
            mode="unidirectional",
            status="closed",
            created_by_session_id="sess-001",
            created_at=now,
            updated_at=now,
            closed_at=now,
            metadata={"key": "val"},
        )
        assert link.closed_at == now
        assert link.metadata == {"key": "val"}
