"""Characterization tests for todo workflow routes."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
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
from teleclaude.api_models import TodoDumpRequest
from teleclaude.core.todos_db import TodosDb


class _ArtifactSnapshot(TypedDict, total=False):
    digest: str
    produced_at: str
    codebase_sha_at_write: str
    referenced_paths: list[str]


class _ArtifactsSnapshot(TypedDict, total=False):
    prd: _ArtifactSnapshot
    requirements: _ArtifactSnapshot


class _TodoStateSnapshot(TypedDict, total=False):
    lifecycle_phase: str
    artifacts: _ArtifactsSnapshot


def _requirements_artifact(state: _TodoStateSnapshot) -> _ArtifactSnapshot:
    artifacts = state.get("artifacts", {})
    return artifacts.get("requirements", {})


async def async_begin() -> AsyncIterator[None]:
    """Async generator that mimics session.begin() context manager."""
    yield


@asynccontextmanager
async def _async_ctx(obj: object) -> AsyncGenerator[object]:
    """Wrap an object as an async context manager."""
    yield obj


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
    def test_local_mutation_routes_are_not_exposed(self) -> None:
        paths = {route.path for route in todo_routes.router.routes if isinstance(route, APIRoute)}
        assert "/todos/stamp/{slug}" not in paths
        assert "/todos/mark-phase/{slug}" not in paths

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
    async def test_todo_set_deps_returns_409_for_circular_dependency(self) -> None:
        """Dependency updates reject cycles discovered by the roadmap graph helper."""
        mock_db = AsyncMock()
        mock_db.slug_in_roadmap = AsyncMock(return_value=True)
        mock_db.load_deps = AsyncMock(return_value={"chartest-api-routes": []})

        with (
            patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db),
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
    async def test_write_artifact_returns_404_when_slug_not_in_roadmap(self) -> None:
        """Artifact writes reject unknown slugs instead of materializing roadmap rows."""
        mock_db = AsyncMock()
        mock_db.slug_in_roadmap = AsyncMock(return_value=False)

        with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db):
            with pytest.raises(HTTPException) as exc_info:
                await todo_routes.write_artifact(
                    slug="missing-slug",
                    name="requirements",
                    content="content",
                    cwd="/repo",
                    updated_by="tester",
                )

        assert exc_info.value.status_code == 404
        mock_db.write_artifact.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_artifact_does_not_auto_progress_phase(self, tmp_path: Path) -> None:
        """Artifact writes preserve content only; lifecycle authority stays on stamps."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap("my-slug")
            await database.write_state("my-slug", {"lifecycle_phase": "prd_drafting"})
            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database):
                response = await todo_routes.write_artifact(
                    slug="my-slug",
                    name="requirements",
                    content="draft requirements",
                    cwd="/repo",
                    updated_by="tester",
                )

            state = await database.read_state("my-slug")
            assert response.status == "ok"
            assert state is not None
            snapshot = cast(_TodoStateSnapshot, state)
            assert snapshot["lifecycle_phase"] == "prd_drafting"
            requirements = _requirements_artifact(snapshot)
            assert requirements.get("digest", "")
            assert requirements.get("produced_at", "") == ""
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_artifact_defaults_updated_by_when_omitted(self, tmp_path: Path) -> None:
        """Route-level artifact writes record their command path when updated_by is omitted."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap("my-slug")
            await database.write_state("my-slug", {"lifecycle_phase": "prd_drafting"})
            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database):
                response = await todo_routes.write_artifact(
                    slug="my-slug",
                    name="requirements",
                    content="draft requirements",
                    cwd="/repo",
                    updated_by=None,
                )

            assert response.status == "ok"
            conn = sqlite3.connect(str(tmp_path / "todos.db"))
            try:
                row = conn.execute(
                    "SELECT updated_by FROM todo_artifacts WHERE slug = ? AND name = ?",
                    ("my-slug", "requirements"),
                ).fetchone()
            finally:
                conn.close()
            assert row is not None
            assert row[0] == "api.todo.write_artifact"
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_write_artifact_records_codebase_provenance_in_state(self, tmp_path: Path) -> None:
        """Route-level artifact writes sync codebase provenance into the typed state entry."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            await database.add_to_roadmap("my-slug")
            await database.write_state("my-slug", {"schema_version": 3, "lifecycle_phase": "prd_drafting"})
            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database):
                response = await todo_routes.write_artifact(
                    slug="my-slug",
                    name="prd",
                    content="touches src/app.py",
                    cwd="/repo",
                    updated_by="tester",
                    codebase_sha_at_write="head-sha",
                    referenced_paths=["src/app.py"],
                )

            state = await database.read_state("my-slug")
            assert response.status == "ok"
            assert state is not None
            artifacts = cast(_TodoStateSnapshot, state)["artifacts"]
            prd = artifacts["prd"]
            assert prd["codebase_sha_at_write"] == "head-sha"
            assert prd["referenced_paths"] == ["src/app.py"]
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_dump_prepped_records_updated_by_on_plan_artifact(self, tmp_path: Path) -> None:
        """Prepped dumps persist implementation-plan provenance on the artifact row."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            request = TodoDumpRequest(
                slug="my-slug",
                content="plan content",
                kind="prepped",
                cwd="/repo",
            )
            with (
                patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database),
                patch("teleclaude.api.todo_routes.apply_prepared_state", return_value={"lifecycle_phase": "prepared"}),
            ):
                response = await todo_routes.todo_dump(request)

            assert response.status == "ok"
            conn = sqlite3.connect(str(tmp_path / "todos.db"))
            try:
                row = conn.execute(
                    "SELECT updated_by FROM todo_artifacts WHERE slug = ? AND name = ?",
                    ("my-slug", "implementation-plan"),
                ).fetchone()
            finally:
                conn.close()
            assert row is not None
            assert row[0] == "api.todo.dump.prepped"
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_remove_returns_receipt(self) -> None:
        """POST /todos/remove returns a 202 receipt via the operations service."""
        mock_operations = AsyncMock()
        mock_operations.submit_todo_remove = AsyncMock(
            return_value={
                "operation_id": "op-123",
                "kind": "todo_remove",
                "state": "queued",
                "poll_after_ms": 250,
                "status_path": "/operations/op-123",
                "recovery_command": "telec operations get op-123",
            }
        )

        with patch("teleclaude.api.todo_routes.get_operations_service", return_value=mock_operations):
            response = await todo_routes.todo_remove(
                slug="test-slug",
                cwd="/repo",
                client_request_id="req-1",
                identity=MagicMock(session_id="session-1"),
            )

        assert response["operation_id"] == "op-123"
        assert response["kind"] == "todo_remove"
        mock_operations.submit_todo_remove.assert_awaited_once_with(
            slug="test-slug",
            cwd="/repo",
            caller_session_id="session-1",
            client_request_id="req-1",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_dump_persists_draft_kind_in_state(self, tmp_path: Path) -> None:
        """POST /todos/dump with kind='draft' must persist kind='draft' in the DB state record."""
        database = TodosDb(str(tmp_path / "todos.db"))
        await database.initialize()
        try:
            with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=database):
                request = TodoDumpRequest(slug="my-draft", content="idea", kind="draft", cwd="/repo")
                response = await todo_routes.todo_dump(request)

            assert response.status == "ok"
            state = await database.read_state("my-draft")
            assert state is not None
            assert state["kind"] == "draft"
            assert state["lifecycle_phase"] == "draft"
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_dump_notifies_via_on_committed_after_transaction(self) -> None:
        """todo_dump calls the public on_committed interface, not _on_mutation directly."""
        mock_db = MagicMock()
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=MagicMock(begin=MagicMock(return_value=_async_ctx(None))))
        session_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_db._session = MagicMock(return_value=session_ctx)
        mock_db.read_state = AsyncMock(return_value=None)
        mock_db.add_to_roadmap = AsyncMock()
        mock_db.write_state = AsyncMock()
        mock_db.write_artifact = AsyncMock()
        mock_db.on_committed = MagicMock()

        with patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db):
            request = TodoDumpRequest(slug="my-draft", content="idea", kind="draft", cwd="/repo")
            await todo_routes.todo_dump(request)

        mock_db.on_committed.assert_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_split_notifies_via_on_committed_after_transaction(self) -> None:
        """todo_split calls the public on_committed interface, not _on_mutation directly."""
        mock_db = MagicMock()
        session_ctx = MagicMock()
        session_ctx.__aenter__ = AsyncMock(return_value=MagicMock(begin=MagicMock(return_value=_async_ctx(None))))
        session_ctx.__aexit__ = AsyncMock(return_value=None)
        mock_db._session = MagicMock(return_value=session_ctx)
        # First call: parent lookup returns existing state; subsequent calls return None (child doesn't exist)
        mock_db.read_state = AsyncMock(side_effect=[{"current": "pending", "breakdown": None}, None])
        mock_db.read_artifact = AsyncMock(return_value=None)
        mock_db.add_to_roadmap = AsyncMock()
        mock_db.write_state = AsyncMock()
        mock_db.on_committed = MagicMock()

        with (
            patch("teleclaude.api.todo_routes._get_todos_db_from_cwd", return_value=mock_db),
            patch("teleclaude.api.todo_routes.StateWriter") as mock_sw,
        ):
            mock_writer = MagicMock()
            mock_writer.state = MagicMock(breakdown=None)
            mock_writer.commit = AsyncMock()
            mock_sw.return_value = mock_writer

            await todo_routes.todo_split(slug="parent", children=["child-1"], cwd="/repo")

        mock_db.on_committed.assert_called()
