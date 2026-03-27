# guard: no-companion
"""working_slug derivation from subdir trees/{slug} pattern.

The session handler derives working_slug from cmd.subdir when the subdir
follows the trees/{slug} convention. Non-trees subdirs and absent subdirs
yield working_slug=None.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest


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


class TestWorkingSlugDerivation:
    """Session handler derives working_slug from subdir via trees/{slug} pattern."""

    @pytest.mark.unit
    async def test_subdir_trees_slug_derives_working_slug(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """subdir='trees/my-slug' must produce working_slug='my-slug'."""
        from teleclaude.core.command_handlers import _session
        from teleclaude.types.commands import CreateSessionCommand

        project_path = tmp_path / "project"
        project_path.mkdir()
        worktree_path = project_path / "trees" / "my-slug"
        worktree_path.mkdir(parents=True)

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
        monkeypatch.setattr(_session, "get_identity_resolver", _admin_resolver)

        cmd = CreateSessionCommand(
            project_path=str(project_path),
            origin="terminal",
            subdir="trees/my-slug",
            origin_metadata={"email": "admin@example.com"},
        )
        await _session.create_session(cmd, MagicMock())

        call_kwargs = db.create_session.call_args[1]
        assert call_kwargs["working_slug"] == "my-slug"

    @pytest.mark.unit
    async def test_subdir_without_trees_prefix_yields_none_working_slug(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """subdir='some-other-dir' must produce working_slug=None."""
        from teleclaude.core.command_handlers import _session
        from teleclaude.types.commands import CreateSessionCommand

        project_path = tmp_path / "project"
        project_path.mkdir()
        other_dir = project_path / "some-other-dir"
        other_dir.mkdir(parents=True)

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

        cmd = CreateSessionCommand(
            project_path=str(project_path),
            origin="terminal",
            subdir="some-other-dir",
            origin_metadata={"email": "admin@example.com"},
        )
        await _session.create_session(cmd, MagicMock())

        call_kwargs = db.create_session.call_args[1]
        assert call_kwargs["working_slug"] is None

    @pytest.mark.unit
    async def test_no_subdir_yields_none_working_slug(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No subdir at all must produce working_slug=None."""
        from teleclaude.core.command_handlers import _session
        from teleclaude.types.commands import CreateSessionCommand

        project_path = tmp_path / "project"
        project_path.mkdir()

        db = SimpleNamespace(
            create_session=AsyncMock(
                return_value=SimpleNamespace(
                    session_id="sess-003",
                    tmux_session_name="tc-sess-003",
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

        cmd = CreateSessionCommand(
            project_path=str(project_path),
            origin="terminal",
            origin_metadata={"email": "admin@example.com"},
        )
        await _session.create_session(cmd, MagicMock())

        call_kwargs = db.create_session.call_args[1]
        assert call_kwargs["working_slug"] is None
