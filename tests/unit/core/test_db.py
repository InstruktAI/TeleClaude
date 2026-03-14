"""Tests for teleclaude.core.db — principal resolution."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from teleclaude.core.db import resolve_session_principal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(
    session_id: str = "sess-001",
    human_email: str | None = None,
    human_role: str | None = None,
    principal: str | None = None,
) -> MagicMock:
    session = MagicMock()
    session.session_id = session_id
    session.human_email = human_email
    session.human_role = human_role
    session.principal = principal
    return session


# ---------------------------------------------------------------------------
# resolve_session_principal
# ---------------------------------------------------------------------------


class TestResolveSessionPrincipal:
    """Tests for the resolve_session_principal() helper."""

    @pytest.mark.unit
    def test_human_session_returns_human_principal(self):
        session = _make_session(human_email="alice@example.com", human_role="admin")
        principal, role = resolve_session_principal(session)
        assert principal == "human:alice@example.com"
        assert role == "admin"

    @pytest.mark.unit
    def test_human_session_defaults_role_to_customer(self):
        session = _make_session(human_email="alice@example.com", human_role=None)
        principal, role = resolve_session_principal(session)
        assert principal == "human:alice@example.com"
        assert role == "customer"

    @pytest.mark.unit
    def test_system_session_uses_full_session_id(self):
        session = _make_session(session_id="abc-def-123", human_email=None)
        principal, role = resolve_session_principal(session)
        assert principal == "system:abc-def-123"
        assert "abc-def-123" in principal
        assert role == "admin"

    @pytest.mark.unit
    def test_anonymous_human_uses_system_principal(self):
        session = _make_session(session_id="anon-123", human_email=None, human_role="customer")
        principal, role = resolve_session_principal(session)
        assert principal == "system:anon-123"
        assert role == "customer"

    @pytest.mark.unit
    def test_system_principal_does_not_truncate_id(self):
        long_id = "a" * 64
        session = _make_session(session_id=long_id, human_email=None)
        principal, _ = resolve_session_principal(session)
        assert long_id in principal
