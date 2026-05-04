"""Typed origin metadata flows through commands and session handler.

Verifies that typed origin metadata objects (WebOriginMetadata, TerminalOriginMetadata)
are preserved through the command → handler → identity resolver → db pipeline without
degrading to raw dicts.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from teleclaude.core.command_handlers import _session
from teleclaude.core.models._adapter import TerminalOriginMetadata, WebOriginMetadata
from teleclaude.types.commands import CreateSessionCommand


def _admin_resolver() -> SimpleNamespace:
    """Return a mock identity resolver that resolves to admin."""

    def _resolve(_origin: str, _metadata: object) -> SimpleNamespace:
        return SimpleNamespace(
            person_email="admin@example.com",
            person_role="admin",
            platform="terminal",
            platform_user_id="admin@example.com",
        )

    return SimpleNamespace(resolve=_resolve)


class TestTypedOriginMetadataOnCommand:
    """Typed origin metadata round-trips through CreateSessionCommand."""

    @pytest.mark.unit
    def test_web_origin_metadata_preserves_email(self) -> None:
        """WebOriginMetadata on a command preserves email for identity resolution."""
        web_meta = WebOriginMetadata(email="test@example.com")
        cmd = CreateSessionCommand(
            project_path="/tmp",
            origin="web",
            origin_metadata=web_meta,
        )
        assert cmd.origin_metadata is not None
        assert cmd.origin_metadata["email"] == "test@example.com"

    @pytest.mark.unit
    def test_terminal_origin_metadata_preserves_email(self) -> None:
        """TerminalOriginMetadata on a command preserves email for identity resolution."""
        term_meta = TerminalOriginMetadata(email="admin@example.com")
        cmd = CreateSessionCommand(
            project_path="/tmp",
            origin="terminal",
            origin_metadata=term_meta,
        )
        assert cmd.origin_metadata is not None
        assert cmd.origin_metadata["email"] == "admin@example.com"


class TestSessionHandlerOriginMetadata:
    """Session handler passes typed origin metadata to the identity resolver and DB."""

    @pytest.mark.unit
    async def test_identity_resolver_receives_typed_metadata(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Identity resolver must receive the typed TerminalOriginMetadata, not a raw dict."""
        project_path = tmp_path / "project"
        project_path.mkdir()

        captured_resolve_args: list[tuple[str, object]] = []

        def _capturing_resolver() -> SimpleNamespace:
            def _resolve(origin: str, metadata: object) -> SimpleNamespace:
                captured_resolve_args.append((origin, metadata))
                return SimpleNamespace(
                    person_email="admin@example.com",
                    person_role="admin",
                    platform="terminal",
                    platform_user_id="admin@example.com",
                )

            return SimpleNamespace(resolve=_resolve)

        db = SimpleNamespace(
            create_session=AsyncMock(
                return_value=SimpleNamespace(
                    session_id="sess-001",
                    tmux_session_name="tc-sess-001",
                )
            ),
            update_session=AsyncMock(),
            update_origin_metadata=AsyncMock(),
            get_session=AsyncMock(return_value=None),
        )
        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(
            _session,
            "config",
            SimpleNamespace(computer=SimpleNamespace(name="local", help_desk_dir=str(tmp_path / "hd"))),
        )
        monkeypatch.setattr(_session, "get_identity_resolver", _capturing_resolver)

        term_meta = TerminalOriginMetadata(email="admin@example.com")
        cmd = CreateSessionCommand(
            project_path=str(project_path),
            origin="terminal",
            origin_metadata=term_meta,
        )
        await _session.create_session(cmd, MagicMock())

        assert len(captured_resolve_args) == 1, "resolve() must be called exactly once"
        origin_arg, metadata_arg = captured_resolve_args[0]
        assert origin_arg == "terminal"
        assert isinstance(metadata_arg, TerminalOriginMetadata)
        assert metadata_arg.email == "admin@example.com"

    @pytest.mark.unit
    async def test_typed_metadata_stored_via_update_origin_metadata(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """update_origin_metadata must receive the typed object, not a degraded dict."""
        project_path = tmp_path / "project"
        project_path.mkdir()

        db = SimpleNamespace(
            create_session=AsyncMock(
                return_value=SimpleNamespace(
                    session_id="sess-002",
                    tmux_session_name="tc-sess-002",
                )
            ),
            update_session=AsyncMock(),
            update_origin_metadata=AsyncMock(),
            get_session=AsyncMock(return_value=None),
        )
        monkeypatch.setattr(_session, "db", db)
        monkeypatch.setattr(
            _session,
            "config",
            SimpleNamespace(computer=SimpleNamespace(name="local", help_desk_dir=str(tmp_path / "hd"))),
        )
        monkeypatch.setattr(_session, "get_identity_resolver", _admin_resolver)

        term_meta = TerminalOriginMetadata(email="admin@example.com")
        cmd = CreateSessionCommand(
            project_path=str(project_path),
            origin="terminal",
            origin_metadata=term_meta,
        )
        await _session.create_session(cmd, MagicMock())

        assert db.update_origin_metadata.called, "update_origin_metadata must be called"
        stored_metadata = db.update_origin_metadata.call_args[0][2]
        # Handler converts Mapping to dict for JSON serialization in the DB layer
        assert isinstance(stored_metadata, dict)
        assert stored_metadata["email"] == "admin@example.com"
