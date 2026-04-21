"""Characterization tests for todo workflow routes."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
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
from teleclaude.core.next_machine._types import PreparePhase, WorkPhase
from teleclaude.core.todos_db import TodosDb
from teleclaude.types.state_value import StateValue


async def async_begin() -> AsyncIterator[None]:
    """Async generator that mimics session.begin() context manager."""
    yield


@asynccontextmanager
async def _async_ctx(obj: object) -> AsyncIterator[object]:
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
    async def test_mark_phase_writes_lifecycle_phase_and_returns_updated_state(self) -> None:
        """mark-phase writes the canonical lifecycle phase and returns updated state."""
        captured: dict[str, StateValue] = {}

        def _fake_write(_cwd: str, _slug: str, state: dict[str, StateValue]) -> None:
            captured["state"] = dict(state)

        prepared_state: dict[str, StateValue] = {
            "requirements_review": {"verdict": "approve"},
            "artifacts": {
                "requirements": {"produced_at": "2026-01-01T00:00:00+00:00"},
                "test_specs": {"produced_at": "2026-01-01T00:00:00+00:00"},
                "implementation_plan": {"produced_at": "2026-01-01T00:00:00+00:00"},
            },
            "test_spec_review": {"verdict": "approve"},
            "plan_review": {"verdict": "approve"},
            "dor": {"score": 8, "status": "pass"},
            "grounding": {"valid": True},
            "lifecycle_phase": "prepared",
            "kind": "bug",
        }

        with (
            patch("teleclaude.api.todo_routes.write_phase_state", _fake_write),
            patch("teleclaude.api.todo_routes.read_phase_state", return_value=prepared_state),
        ):
            response = await todo_routes.mark_phase(
                slug="chartest-api-routes",
                phase=PreparePhase.PREPARED.value,
                cwd="/repo",
            )

        persisted = captured.get("state", {})
        assert isinstance(persisted, dict)
        assert persisted.get("lifecycle_phase") == PreparePhase.PREPARED.value
        assert isinstance(response, dict)
        assert response.get("lifecycle_phase") == PreparePhase.PREPARED.value
        assert response.get("kind") == "bug"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mark_phase_writes_work_target_when_prerequisites_hold(self) -> None:
        """Work lifecycle targets persist through the canonical lifecycle field."""
        captured: dict[str, StateValue] = {}

        def _fake_write(_cwd: str, _slug: str, state: dict[str, StateValue]) -> None:
            captured["state"] = dict(state)

        prepared_state: dict[str, StateValue] = {
            "requirements_review": {"verdict": "approve"},
            "artifacts": {
                "requirements": {"produced_at": "2026-01-01T00:00:00+00:00"},
                "test_specs": {"produced_at": "2026-01-01T00:00:00+00:00"},
                "implementation_plan": {"produced_at": "2026-01-01T00:00:00+00:00"},
            },
            "test_spec_review": {"verdict": "approve"},
            "plan_review": {"verdict": "approve"},
            "dor": {"score": 8, "status": "pass"},
            "grounding": {"valid": True},
            "lifecycle_phase": "prepared",
        }

        with (
            patch("teleclaude.api.todo_routes.write_phase_state", _fake_write),
            patch("teleclaude.api.todo_routes.read_phase_state", return_value=prepared_state),
        ):
            response = await todo_routes.mark_phase(
                slug="chartest-api-routes",
                phase=WorkPhase.BUILD_STARTED.value,
                cwd="/repo",
            )

        persisted = captured.get("state", {})
        assert isinstance(persisted, dict)
        assert persisted.get("lifecycle_phase") == WorkPhase.BUILD_STARTED.value
        assert isinstance(response, dict)
        assert response.get("lifecycle_phase") == WorkPhase.BUILD_STARTED.value

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
        finally:
            await database.close()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mark_phase_rejects_unknown_phase_value_with_400(self) -> None:
        """Unknown phase values yield HTTP 400 and list both enums' valid values."""
        with pytest.raises(HTTPException) as exc_info:
            await todo_routes.mark_phase(
                slug="chartest-api-routes",
                phase="not_a_real_phase",
                cwd="/repo",
            )

        assert exc_info.value.status_code == 400
        detail = exc_info.value.detail
        assert isinstance(detail, str)
        assert PreparePhase.PREPARED.value in detail
        assert WorkPhase.BUILD_STARTED.value in detail
