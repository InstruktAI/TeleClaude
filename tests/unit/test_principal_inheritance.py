"""Unit tests for principal inheritance across the session spawn chain.

Task 7.4 — covers:
- channel_metadata principal threading into db.create_session
- parent session principal inheritance when metadata absent
- daemon bootstrap principal selection via resolve_session_principal
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.db import resolve_session_principal

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_session(
    session_id: str = "sess-parent",
    principal: str | None = "system:sess-parent",
    human_email: str | None = None,
    human_role: str | None = "admin",
) -> MagicMock:
    session = MagicMock()
    session.session_id = session_id
    session.principal = principal
    session.human_email = human_email
    session.human_role = human_role
    return session


def _make_create_cmd(
    channel_metadata: dict[str, object] | None = None,
    initiator_session_id: str | None = None,
) -> object:
    """Build a minimal CreateSessionCommand."""
    from teleclaude.types.commands import CreateSessionCommand

    return CreateSessionCommand(
        project_path="/tmp/project",
        origin="api",
        channel_metadata=channel_metadata,
        initiator_session_id=initiator_session_id,
    )


async def _run_create_session(
    cmd: object,
    parent_session: MagicMock | None = None,
    working_dir: str = "/tmp/project",
) -> dict[str, object]:
    """Call create_session with mocked dependencies, return the kwargs passed to db.create_session."""
    from pathlib import Path as _RealPath

    from teleclaude.core.command_handlers import create_session

    captured: dict[str, object] = {}

    async def _capture_create(**kwargs: object) -> MagicMock:
        captured.update(kwargs)
        session = MagicMock()
        session.session_id = "sess-child"
        return session

    client = MagicMock()

    # Build a fake Path that passes all validation checks without touching the filesystem.
    fake_path = MagicMock(spec=_RealPath)
    fake_path.is_absolute.return_value = True
    fake_path.exists.return_value = True
    fake_path.is_dir.return_value = True
    fake_path.__str__ = MagicMock(return_value=working_dir)
    fake_path.__fspath__ = MagicMock(return_value=working_dir)
    fake_path.mkdir = MagicMock()

    with (
        patch("teleclaude.core.command_handlers.db") as mock_db,
        patch("teleclaude.core.command_handlers.get_identity_resolver") as mock_resolver,
        patch("teleclaude.core.command_handlers.resolve_working_dir", return_value=working_dir),
        patch("teleclaude.core.command_handlers.config") as mock_config,
        patch("teleclaude.core.command_handlers.Path", return_value=fake_path),
    ):
        mock_db.get_session = AsyncMock(return_value=parent_session)
        mock_db.create_session = AsyncMock(side_effect=_capture_create)
        mock_resolver.return_value.resolve.return_value = None
        mock_config.computer = MagicMock()
        mock_config.computer.name = "local"
        mock_config.computer.help_desk_dir = None

        await create_session(cmd, client)

    return captured


# ---------------------------------------------------------------------------
# Principal resolution in create_session metadata path
# ---------------------------------------------------------------------------


class TestCreateSessionPrincipalInheritance:
    """channel_metadata and parent session principal flow into db.create_session."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_principal_from_channel_metadata_wins_over_parent(self):
        """Metadata principal takes precedence over parent session principal."""
        parent_session = _make_session(principal="system:parent-principal")
        cmd = _make_create_cmd(
            channel_metadata={"principal": "system:override-principal"},
            initiator_session_id="sess-parent",
        )

        captured = await _run_create_session(cmd, parent_session)
        assert captured.get("principal") == "system:override-principal"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_parent_principal_used_when_metadata_absent(self):
        """When channel_metadata has no principal, parent session principal is inherited."""
        parent_session = _make_session(principal="system:parent-principal")
        cmd = _make_create_cmd(
            channel_metadata={},
            initiator_session_id="sess-parent",
        )

        captured = await _run_create_session(cmd, parent_session)
        assert captured.get("principal") == "system:parent-principal"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_no_principal_when_both_absent(self):
        """When neither metadata nor parent has a principal, result is None."""
        parent_session = _make_session(principal=None)
        cmd = _make_create_cmd(
            channel_metadata={},
            initiator_session_id="sess-parent",
        )

        captured = await _run_create_session(cmd, parent_session)
        assert captured.get("principal") is None


# ---------------------------------------------------------------------------
# Daemon bootstrap principal selection — tests resolve_session_principal
# directly (the canonical function the daemon calls unconditionally).
# ---------------------------------------------------------------------------


class TestDaemonBootstrapPrincipalSelection:
    """resolve_session_principal handles all bootstrap cases."""

    @pytest.mark.unit
    def test_inherited_principal_used_directly(self):
        """resolve_session_principal uses session.principal when already set."""
        session = _make_session(session_id="sess-child", principal="system:sess-parent")
        principal, role = resolve_session_principal(session)
        assert principal == "system:sess-parent"
        assert role == "admin"

    @pytest.mark.unit
    def test_derives_system_principal_when_none_inherited(self):
        """Derives system:<session_id> when session has no principal."""
        session = _make_session(session_id="sess-fresh", principal=None, human_email=None)
        principal, role = resolve_session_principal(session)
        assert principal == "system:sess-fresh"
        assert role == "admin"

    @pytest.mark.unit
    def test_derives_human_principal_from_email(self):
        """Derives human:<email> principal from session.human_email."""
        session = _make_session(
            session_id="sess-001",
            principal=None,
            human_email="alice@example.com",
            human_role="admin",
        )
        principal, role = resolve_session_principal(session)
        assert principal == "human:alice@example.com"
        assert role == "admin"

    @pytest.mark.unit
    def test_inherited_principal_preserves_full_session_id(self):
        """An inherited principal with a long session_id is never truncated."""
        long_id = "a" * 64
        session = _make_session(session_id=long_id, principal=f"system:{long_id}")
        principal, _ = resolve_session_principal(session)
        assert long_id in principal

    @pytest.mark.unit
    def test_principal_chain_shares_same_identity(self):
        """Agent -> child agent chain preserves the same principal string."""
        parent_principal = "system:root-sess"
        agent_session = _make_session(session_id="agent-sess", principal=parent_principal)
        child_session = _make_session(session_id="child-sess", principal=parent_principal)

        agent_principal, _ = resolve_session_principal(agent_session)
        child_principal, _ = resolve_session_principal(child_session)

        assert agent_principal == parent_principal
        assert child_principal == parent_principal
        assert agent_principal == child_principal
