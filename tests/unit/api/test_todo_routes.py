"""Characterization tests for todo workflow routes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from typing_extensions import TypedDict

from teleclaude.api import todo_routes
from teleclaude.api.auth import CallerIdentity


class _TodoIntegrateReceipt(TypedDict):
    operation_id: str
    kind: str
    state: str
    poll_after_ms: int
    status_path: str
    recovery_command: str


def _identity(session_id: str = "sess-1") -> CallerIdentity:
    return CallerIdentity(
        session_id=session_id,
        system_role=None,
        human_role=None,
        tmux_session_name=None,
    )


class TestTodoRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_create_uses_default_cwd_when_request_omits_it(self) -> None:
        """Todo creation falls back to the configured default working directory."""
        config_stub = SimpleNamespace(computer=SimpleNamespace(default_working_dir="/repo"))
        mock_ops = MagicMock()
        mock_ops.submit_todo_create = AsyncMock(
            return_value={
                "operation_id": "op-1",
                "kind": "todo_create",
                "state": "queued",
                "poll_after_ms": 250,
                "status_path": "/operations/op-1",
            }
        )

        with (
            patch("teleclaude.api.todo_routes.config", config_stub),
            patch("teleclaude.api.todo_routes.get_operations_service", return_value=mock_ops),
        ):
            response = await todo_routes.todo_create(
                slug="chartest-api-routes",
                cwd=None,
                client_request_id=None,
                _identity=_identity(),
            )

        assert response["operation_id"] == "op-1"
        mock_ops.submit_todo_create.assert_awaited_once()
        call_kwargs = mock_ops.submit_todo_create.call_args.kwargs
        assert call_kwargs["cwd"] == "/repo"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_work_requires_explicit_cwd(self) -> None:
        """Todo work submissions reject requests without a working directory."""
        with pytest.raises(HTTPException) as exc_info:
            await todo_routes.todo_work(
                slug="chartest-api-routes", cwd=None, client_request_id=None, identity=_identity()
            )

        assert exc_info.value.status_code == 400

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_integrate_requires_cwd(self) -> None:
        """Todo integrate submissions reject requests without a working directory."""
        with pytest.raises(HTTPException) as exc_info:
            await todo_routes.todo_integrate(slug="chartest-api-routes", cwd=None, identity=_identity())

        assert exc_info.value.status_code == 400

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_integrate_returns_202_receipt(self) -> None:
        """Todo integrate should submit an operation receipt instead of blocking inline."""
        receipt: _TodoIntegrateReceipt = {
            "operation_id": "op-1",
            "kind": "todo_integrate",
            "state": "queued",
            "poll_after_ms": 250,
            "status_path": "/operations/op-1",
            "recovery_command": "telec operations get op-1",
        }
        operations = MagicMock()
        operations.submit_todo_integrate = AsyncMock(return_value=receipt)
        todo_integrate = cast(Callable[..., Awaitable[_TodoIntegrateReceipt]], todo_routes.todo_integrate)
        integrate_route = next(
            route
            for route in todo_routes.router.routes
            if isinstance(route, APIRoute) and route.path == "/todos/integrate"
        )

        with patch("teleclaude.api.todo_routes.get_operations_service", return_value=operations):
            response = await todo_integrate(
                slug="chartest-api-routes",
                cwd="/repo",
                client_request_id="req-1",
                identity=_identity(),
            )

        assert integrate_route.status_code == 202
        assert response == receipt
        operations.submit_todo_integrate.assert_awaited_once_with(
            slug="chartest-api-routes",
            cwd="/repo",
            caller_session_id="sess-1",
            client_request_id="req-1",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_mark_phase_rejects_invalid_prepare_status(self) -> None:
        """Prepare-phase updates validate the allowed status vocabulary before mutating state."""
        with pytest.raises(HTTPException) as exc_info:
            await todo_routes.todo_mark_phase(
                slug="chartest-api-routes",
                phase="prepare",
                status="bogus",
                cwd="/repo",
                _identity=_identity(),
            )

        assert exc_info.value.status_code == 400

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_set_deps_returns_409_for_circular_dependency(self) -> None:
        """Dependency updates reject cycles discovered by the roadmap graph helper."""
        entries = [SimpleNamespace(slug="chartest-api-routes", after=[]), SimpleNamespace(slug="base-task", after=[])]

        with (
            patch("teleclaude.api.todo_routes.load_roadmap", return_value=entries),
            patch("teleclaude.api.todo_routes.load_roadmap_deps", return_value={"chartest-api-routes": []}),
            patch("teleclaude.api.todo_routes.detect_circular_dependency", return_value=["a", "b", "a"]),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await todo_routes.todo_set_deps(
                    slug="chartest-api-routes",
                    after=["base-task"],
                    cwd="/repo",
                    _identity=_identity(),
                )

        assert exc_info.value.status_code == 409

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_set_deps_persists_updated_dependency_list(self) -> None:
        """Successful dependency updates rewrite the roadmap entry and save the roadmap."""
        entries = [SimpleNamespace(slug="chartest-api-routes", after=[]), SimpleNamespace(slug="base-task", after=[])]

        with (
            patch("teleclaude.api.todo_routes.load_roadmap", return_value=entries),
            patch("teleclaude.api.todo_routes.load_roadmap_deps", return_value={"chartest-api-routes": []}),
            patch("teleclaude.api.todo_routes.detect_circular_dependency", return_value=None),
            patch("teleclaude.api.todo_routes.save_roadmap", new=MagicMock()) as save_roadmap,
        ):
            response = await todo_routes.todo_set_deps(
                slug="chartest-api-routes",
                after=["base-task"],
                cwd="/repo",
                _identity=_identity(),
            )

        assert "result" in response
        assert response["result"]  # non-empty result present
        assert entries[0].after == ["base-task"]
        save_roadmap.assert_called_once_with("/repo", entries)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mark_phase_build_complete_force_skips_uncommitted_check(self, tmp_path: Path) -> None:
        """Force flag bypasses uncommitted-changes guard for build:complete."""
        worktree = tmp_path / "trees" / "test-slug"
        worktree.mkdir(parents=True)
        mock_repo = MagicMock()
        mock_repo.git.diff.return_value = ""
        with (
            patch("teleclaude.api.todo_routes.WORKTREE_DIR", "trees"),
            patch("teleclaude.api.todo_routes.has_uncommitted_changes", return_value=True),
            patch("teleclaude.api.todo_routes.mark_phase", return_value={"build": "complete"}) as mock_mark,
            patch("teleclaude.git.Repo", return_value=mock_repo),
        ):
            response = await todo_routes.todo_mark_phase(
                slug="test-slug",
                phase="build",
                status="complete",
                cwd=str(tmp_path),
                _identity=_identity(),
                force=True,
            )
        assert "result" in response
        mock_mark.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mark_phase_review_approved_no_longer_blocks_on_uncommitted(self, tmp_path: Path) -> None:
        """Review:approved no longer checks for uncommitted changes."""
        worktree = tmp_path / "trees" / "test-slug"
        worktree.mkdir(parents=True)
        mock_repo = MagicMock()
        mock_repo.git.diff.return_value = ""
        with (
            patch("teleclaude.api.todo_routes.WORKTREE_DIR", "trees"),
            patch("teleclaude.api.todo_routes.has_uncommitted_changes", return_value=True) as mock_uc,
            patch("teleclaude.api.todo_routes.mark_phase", return_value={"review": "approved"}) as mock_mark,
            patch("teleclaude.git.Repo", return_value=mock_repo),
        ):
            response = await todo_routes.todo_mark_phase(
                slug="test-slug",
                phase="review",
                status="approved",
                cwd=str(tmp_path),
                _identity=_identity(),
            )
        assert "result" in response
        mock_mark.assert_called_once()
        mock_uc.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mark_phase_stash_no_longer_blocks_any_phase(self, tmp_path: Path) -> None:
        """Stash entries no longer block any phase transition."""
        worktree = tmp_path / "trees" / "test-slug"
        worktree.mkdir(parents=True)
        mock_repo = MagicMock()
        mock_repo.git.diff.return_value = ""
        with (
            patch("teleclaude.api.todo_routes.WORKTREE_DIR", "trees"),
            patch("teleclaude.api.todo_routes.has_uncommitted_changes", return_value=False),
            patch("teleclaude.api.todo_routes.mark_phase", return_value={"build": "complete"}) as mock_mark,
            patch("teleclaude.git.Repo", return_value=mock_repo),
        ):
            response = await todo_routes.todo_mark_phase(
                slug="test-slug",
                phase="build",
                status="complete",
                cwd=str(tmp_path),
                _identity=_identity(),
            )
        assert "result" in response
        mock_mark.assert_called_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mark_phase_force_falls_back_to_cwd_when_no_worktree(self, tmp_path: Path) -> None:
        """Force flag uses cwd when worktree directory does not exist."""
        mock_repo = MagicMock()
        mock_repo.git.diff.return_value = ""
        with (
            patch("teleclaude.api.todo_routes.WORKTREE_DIR", "trees"),
            patch("teleclaude.api.todo_routes.mark_phase", return_value={"build": "pending"}) as mock_mark,
            patch("teleclaude.git.Repo", return_value=mock_repo),
        ):
            response = await todo_routes.todo_mark_phase(
                slug="test-slug",
                phase="build",
                status="pending",
                cwd=str(tmp_path),
                _identity=_identity(),
                force=True,
            )
        assert "result" in response
        mock_mark.assert_called_once_with(str(tmp_path), "test-slug", "build_pending")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mark_phase_no_force_still_404_when_worktree_absent(self, tmp_path: Path) -> None:
        """Without force, missing worktree still returns 404."""
        with (
            patch("teleclaude.api.todo_routes.WORKTREE_DIR", "trees"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await todo_routes.todo_mark_phase(
                    slug="test-slug",
                    phase="build",
                    status="pending",
                    cwd=str(tmp_path),
                    _identity=_identity(),
                )
        assert exc_info.value.status_code == 404

    # ------------------------------------------------------------------
    # New target= path tests (I-3)
    # ------------------------------------------------------------------

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mark_phase_target_happy_path(self, tmp_path: Path) -> None:
        """target= path calls mark_phase and auto-commits state (non-build-terminal target)."""
        mock_repo = MagicMock()
        mock_repo.git.diff.return_value = ""
        with (
            patch("teleclaude.api.todo_routes.mark_phase", return_value={"current": "build_started"}) as mock_mark,
            patch("teleclaude.git.Repo", return_value=mock_repo),
        ):
            response = await todo_routes.todo_mark_phase(
                slug="test-slug",
                target="build_started",
                cwd=str(tmp_path),
                _identity=_identity(),
            )
        assert "result" in response
        assert "OK:" in response["result"]
        mock_mark.assert_called_once_with(str(tmp_path), "test-slug", "build_started")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mark_phase_target_returns_409_on_value_error(self, tmp_path: Path) -> None:
        """target= path converts ValueError from mark_phase to 409."""
        with (
            patch("teleclaude.api.todo_routes.mark_phase", side_effect=ValueError("transition not allowed")),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await todo_routes.todo_mark_phase(
                    slug="test-slug",
                    target="build_started",
                    cwd=str(tmp_path),
                    _identity=_identity(),
                )
        assert exc_info.value.status_code == 409
        assert "transition not allowed" in exc_info.value.detail

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mark_phase_target_404_when_build_terminal_and_no_worktree(self, tmp_path: Path) -> None:
        """target= path returns 404 when a build-terminal target requires a worktree that is absent."""
        with (
            patch("teleclaude.api.todo_routes.WORKTREE_DIR", "trees"),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await todo_routes.todo_mark_phase(
                    slug="test-slug",
                    target="build_complete",
                    cwd=str(tmp_path),
                    _identity=_identity(),
                )
        assert exc_info.value.status_code == 404

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mark_phase_target_400_when_cwd_missing(self) -> None:
        """target= path rejects request when cwd is absent."""
        with pytest.raises(HTTPException) as exc_info:
            await todo_routes.todo_mark_phase(
                slug="test-slug",
                target="review_pending",
                cwd=None,
                _identity=_identity(),
            )
        assert exc_info.value.status_code == 400

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mark_phase_target_build_complete_blocks_uncommitted_changes(self, tmp_path: Path) -> None:
        """target=build_complete raises 409 when worktree has uncommitted changes."""
        worktree = tmp_path / "trees" / "test-slug"
        worktree.mkdir(parents=True)
        with (
            patch("teleclaude.api.todo_routes.WORKTREE_DIR", "trees"),
            patch("teleclaude.api.todo_routes.has_uncommitted_changes", return_value=True),
        ):
            with pytest.raises(HTTPException) as exc_info:
                await todo_routes.todo_mark_phase(
                    slug="test-slug",
                    target="build_complete",
                    cwd=str(tmp_path),
                    _identity=_identity(),
                )
        assert exc_info.value.status_code == 409
