"""Tests for teleclaude.core.session_cleanup — session termination and token revocation."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from teleclaude.core import session_cleanup
from teleclaude.core.session_cleanup import (
    _end_escalation_if_active,
    _terminate_session_inner,
    cleanup_orphan_session_tmpdirs,
    cleanup_orphan_workspaces,
    cleanup_session_tmpdir,
)


def _make_session(session_id: str = "sess-lifecycle") -> MagicMock:
    session = MagicMock()
    session.session_id = session_id
    session.principal = f"system:{session_id}"
    session.human_email = None
    session.human_role = "admin"
    session.tmux_session_name = f"tmux-{session_id}"
    session.project_path = "/tmp/project"
    session.subdir = None
    return session


class TestTerminateSessionRevokesTokens:
    """Closing a session triggers revoke_session_tokens() and cache invalidation."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_terminate_session_calls_revoke_and_invalidate(self):
        """terminate_session calls revoke_session_tokens and invalidate_token_cache."""
        session = _make_session(session_id="sess-lifecycle")

        with (
            patch("teleclaude.core.session_cleanup.db") as mock_db,
            patch("teleclaude.core.session_cleanup.invalidate_token_cache") as mock_invalidate,
            patch("teleclaude.core.session_cleanup.tmux_bridge") as mock_tmux,
            patch("teleclaude.core.session_cleanup.cleanup_session_resources", new_callable=AsyncMock),
            patch("teleclaude.core.session_cleanup.event_bus") as mock_event_bus,
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.revoke_session_tokens = AsyncMock()
            mock_db.update_session = AsyncMock()
            mock_db.close_session = AsyncMock()
            mock_tmux.kill_session = AsyncMock(return_value=True)
            mock_event_bus.emit = AsyncMock()

            await _terminate_session_inner("sess-lifecycle", MagicMock(), reason="test")

        mock_db.revoke_session_tokens.assert_called_once_with("sess-lifecycle")
        mock_invalidate.assert_called_once_with("sess-lifecycle")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_terminate_closes_db_even_when_tmpdir_cleanup_raises(self) -> None:
        """Regression: cleanup_session_tmpdir crashing must not strand session at lifecycle=closing.

        Once tmux is killed the session is unrecoverable from the user's view, so the DB
        close at the end must always run — otherwise the TUI keeps trying to attach to a
        dead tmux session and the session never emits SESSION_CLOSED.
        """
        session = _make_session(session_id="sess-lifecycle")
        session.closed_at = None

        async def _boom(_session_id: str) -> bool:
            raise FileNotFoundError("simulated rmtree race on node-compile-cache")

        with (
            patch("teleclaude.core.session_cleanup.db") as mock_db,
            patch("teleclaude.core.session_cleanup.invalidate_token_cache"),
            patch("teleclaude.core.session_cleanup.tmux_bridge") as mock_tmux,
            patch("teleclaude.core.session_cleanup.cleanup_session_resources", new_callable=AsyncMock),
            patch(
                "teleclaude.core.session_cleanup.cleanup_session_tmpdir",
                new=AsyncMock(side_effect=_boom),
            ),
            patch("teleclaude.core.session_cleanup.event_bus"),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.revoke_session_tokens = AsyncMock()
            mock_db.update_session = AsyncMock()
            mock_db.close_session = AsyncMock()
            mock_tmux.kill_session = AsyncMock(return_value=True)

            await _terminate_session_inner("sess-lifecycle", MagicMock(), reason="test")

        mock_db.close_session.assert_called_once_with("sess-lifecycle")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_terminate_session_removes_tmpdir_after_resource_cleanup(self) -> None:
        session = _make_session(session_id="sess-lifecycle")
        order: list[str] = []

        async def _record_resource_cleanup(*_args: object, **_kwargs: object) -> None:
            order.append("resources")

        async def _record_tmp_cleanup(_session_id: str) -> bool:
            order.append("tmpdir")
            return True

        with (
            patch("teleclaude.core.session_cleanup.db") as mock_db,
            patch("teleclaude.core.session_cleanup.invalidate_token_cache"),
            patch("teleclaude.core.session_cleanup.tmux_bridge") as mock_tmux,
            patch(
                "teleclaude.core.session_cleanup.cleanup_session_resources",
                new=AsyncMock(side_effect=_record_resource_cleanup),
            ),
            patch(
                "teleclaude.core.session_cleanup.cleanup_session_tmpdir",
                new=AsyncMock(side_effect=_record_tmp_cleanup),
            ),
            patch("teleclaude.core.session_cleanup.event_bus"),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.revoke_session_tokens = AsyncMock()
            mock_db.update_session = AsyncMock()
            mock_db.close_session = AsyncMock()
            mock_tmux.kill_session = AsyncMock(return_value=True)

            await _terminate_session_inner("sess-lifecycle", MagicMock(), reason="test")

        assert order == ["resources", "tmpdir"]


class TestSessionTmpdirCleanup:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cleanup_session_tmpdir_removes_owned_directory(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        session_id = str(uuid4())
        monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path))
        session_tmpdir = tmp_path / session_id
        session_tmpdir.mkdir()
        (session_tmpdir / "teleclaude_identity.json").write_text("{}", encoding="utf-8")

        removed = await cleanup_session_tmpdir(session_id)

        assert removed is True
        assert not session_tmpdir.exists()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_cleanup_session_tmpdir_tolerates_files_vanishing_mid_walk(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Regression: Node's compile-cache deletes files while shutil.rmtree walks.

        The cleanup must treat FileNotFoundError as benign — otherwise the surrounding
        terminate_session call strands the session at lifecycle=closing. This test
        forces a real FileNotFoundError from inside rmtree's walk (via os.unlink) to
        ensure the production onexc handler swallows it; without that handler the
        exception would propagate.
        """
        session_id = str(uuid4())
        monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path))
        session_tmpdir = tmp_path / session_id
        nested = session_tmpdir / "node-compile-cache" / "v26"
        nested.mkdir(parents=True)
        victim_name = "abc.cache"
        (nested / victim_name).write_text("x", encoding="utf-8")

        real_unlink = os.unlink
        raised = {"done": False}

        def _racy_unlink(target: object, /, **kwargs: object) -> None:
            # Mimic Node deleting the file just before rmtree's _rmtree_safe_fd
            # unlinks it: actually remove the file first, then raise FileNotFoundError
            # the way the kernel would have. rmtree must accept that the file is gone
            # so the parent rmdir still succeeds.
            name = target if isinstance(target, str) else getattr(target, "name", "")
            if not raised["done"] and name == victim_name:
                raised["done"] = True
                real_unlink(target, **kwargs)
                raise FileNotFoundError(2, "No such file or directory", str(target))
            real_unlink(target, **kwargs)

        with patch("os.unlink", side_effect=_racy_unlink):
            removed = await cleanup_session_tmpdir(session_id)

        assert raised["done"], "test setup failed: victim unlink was not intercepted"
        assert removed is True
        assert not session_tmpdir.exists()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_orphan_tmpdir_reconciliation_removes_only_safe_closed_or_missing_dirs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        open_id = str(uuid4())
        closed_id = str(uuid4())
        missing_id = str(uuid4())
        young_missing_id = str(uuid4())
        artifact_slug = "runtime-state-maintenance-automation"
        for dirname in [open_id, closed_id, missing_id, young_missing_id, artifact_slug]:
            (tmp_path / dirname).mkdir()
        symlink_path = tmp_path / str(uuid4())
        symlink_path.symlink_to(tmp_path / open_id, target_is_directory=True)
        old_mtime = (datetime.now(UTC) - timedelta(hours=1)).timestamp()
        for dirname in [open_id, closed_id, missing_id, artifact_slug]:
            path = tmp_path / dirname
            path.touch()
            os.utime(path, (old_mtime, old_mtime))

        open_session = MagicMock(session_id=open_id, closed_at=None, lifecycle_status="active")
        closed_session = MagicMock(session_id=closed_id, closed_at=datetime.now(UTC), lifecycle_status="closed")
        monkeypatch.setenv("TELECLAUDE_SESSION_TMPDIR_BASE", str(tmp_path))

        with patch(
            "teleclaude.core.session_cleanup.db.get_all_sessions",
            new=AsyncMock(return_value=[open_session, closed_session]),
        ):
            removed = await cleanup_orphan_session_tmpdirs(race_safety_age=timedelta(minutes=10))

        assert removed == 2
        assert (tmp_path / open_id).exists()
        assert not (tmp_path / closed_id).exists()
        assert not (tmp_path / missing_id).exists()
        assert (tmp_path / young_missing_id).exists()
        assert (tmp_path / artifact_slug).exists()
        assert symlink_path.exists()


class TestWorkspaceCleanup:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_workspace_cleanup_ignores_non_session_artifact_slug_dirs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        orphan_session_id = str(uuid4())
        active_session_id = str(uuid4())
        artifact_slug = "runtime-state-maintenance-automation"
        for dirname in [orphan_session_id, active_session_id, artifact_slug]:
            (tmp_path / dirname).mkdir()
        active_session = MagicMock(session_id=active_session_id)
        monkeypatch.setattr(session_cleanup, "OUTPUT_DIR", tmp_path)

        with patch("teleclaude.core.session_cleanup.db.get_all_sessions", new=AsyncMock(return_value=[active_session])):
            removed = await cleanup_orphan_workspaces()

        assert removed == 1
        assert not (tmp_path / orphan_session_id).exists()
        assert (tmp_path / active_session_id).exists()
        assert (tmp_path / artifact_slug).exists()


class TestEndEscalationIfActive:
    """_end_escalation_if_active clears relay state and emits event when escalated."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_active_escalation_is_cleared_and_event_emitted(self):
        session = _make_session(session_id="sess-esc")
        session.relay_status = "active"

        with (
            patch("teleclaude.core.session_cleanup.db") as mock_db,
            patch("teleclaude.core.session_cleanup.event_bus") as mock_event_bus,
        ):
            mock_db.update_session = AsyncMock()

            await _end_escalation_if_active(session)

        mock_db.update_session.assert_called_once_with(
            "sess-esc",
            relay_status=None,
            relay_discord_channel_id=None,
            relay_started_at=None,
        )
        mock_event_bus.emit.assert_called_once()
        assert mock_event_bus.emit.call_args.args[0] == "session.escalation_ended"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_non_escalated_session_is_skipped(self):
        session = _make_session(session_id="sess-no-esc")
        session.relay_status = None

        with (
            patch("teleclaude.core.session_cleanup.db") as mock_db,
            patch("teleclaude.core.session_cleanup.event_bus") as mock_event_bus,
        ):
            mock_db.update_session = AsyncMock()

            await _end_escalation_if_active(session)

        mock_db.update_session.assert_not_called()
        mock_event_bus.emit.assert_not_called()
