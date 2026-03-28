# guard: no-companion
"""Test specifications for FR-3: Receipt-backed operation handling for heavy endpoints.

Todo create and todo prepare must be migrated to the receipt-backed operation pattern:
persist operation row, return receipt immediately (202), execute in background,
emit completion event on terminal transition.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestTodoCreateReturnsReceipt:
    """POST /todos/create returns an operation receipt (202) instead of blocking."""

    @pytest.mark.unit
    def test_todo_create_route_returns_202(self) -> None:
        """The /todos/create route is registered with status_code=202."""
        from fastapi.routing import APIRoute

        from teleclaude.api.todo_routes import router

        create_route = next(
            route for route in router.routes if isinstance(route, APIRoute) and route.path == "/todos/create"
        )
        assert create_route.status_code == 202

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_create_returns_receipt_with_operation_id(self) -> None:
        """Todo create response contains an operation_id for polling."""
        from teleclaude.api import todo_routes
        from teleclaude.api.auth import CallerIdentity

        operations = MagicMock()
        operations.submit_todo_create = AsyncMock(
            return_value={
                "operation_id": "op-create-1",
                "kind": "todo_create",
                "state": "queued",
                "poll_after_ms": 250,
                "status_path": "/operations/op-create-1",
            }
        )
        identity = CallerIdentity(session_id="sess-1", system_role=None, human_role=None, tmux_session_name=None)

        with patch("teleclaude.api.todo_routes.get_operations_service", return_value=operations):
            response = await todo_routes.todo_create(slug="test-slug", cwd="/repo", _identity=identity)

        assert response.get("operation_id") == "op-create-1"
        assert response.get("kind") == "todo_create"
        assert response.get("state") == "queued"

    @pytest.mark.unit
    def test_todo_create_accepts_client_request_id_parameter(self) -> None:
        """Todo create route signature accepts client_request_id for idempotent submissions."""
        import inspect

        from teleclaude.api.todo_routes import todo_create

        sig = inspect.signature(todo_create)
        assert "client_request_id" in sig.parameters


class TestTodoPrepareReturnsReceipt:
    """POST /todos/prepare returns an operation receipt (202) instead of blocking."""

    @pytest.mark.unit
    def test_todo_prepare_route_returns_202(self) -> None:
        """The /todos/prepare route is registered with status_code=202."""
        from fastapi.routing import APIRoute

        from teleclaude.api.todo_routes import router

        prepare_route = next(
            route for route in router.routes if isinstance(route, APIRoute) and route.path == "/todos/prepare"
        )
        assert prepare_route.status_code == 202

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_todo_prepare_returns_receipt_with_operation_id(self) -> None:
        """Todo prepare response contains an operation_id for polling."""
        from teleclaude.api import todo_routes
        from teleclaude.api.auth import CallerIdentity

        operations = MagicMock()
        operations.submit_todo_prepare = AsyncMock(
            return_value={
                "operation_id": "op-prep-1",
                "kind": "todo_prepare",
                "state": "queued",
                "poll_after_ms": 250,
                "status_path": "/operations/op-prep-1",
            }
        )
        identity = CallerIdentity(session_id="sess-1", system_role=None, human_role=None, tmux_session_name=None)

        with patch("teleclaude.api.todo_routes.get_operations_service", return_value=operations):
            response = await todo_routes.todo_prepare(slug="test-slug", cwd="/repo", _identity=identity)

        assert response.get("operation_id") == "op-prep-1"
        assert response.get("kind") == "todo_prepare"
        assert response.get("state") == "queued"


class TestCompletionEventEmissionOnTerminalTransition:
    """Receipt-backed operations emit a completion event when reaching terminal state."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_parametric_runner_handles_all_operation_kinds(self) -> None:
        """The parametric _run_operation runner emits completion events for
        all operation kinds, including todo_create and todo_prepare."""
        from teleclaude.core.operations.service import (
            _COMPLETION_EVENTS,
            OPERATION_KIND_TODO_CREATE,
            OPERATION_KIND_TODO_PREPARE,
        )

        assert OPERATION_KIND_TODO_CREATE in _COMPLETION_EVENTS
        assert OPERATION_KIND_TODO_PREPARE in _COMPLETION_EVENTS


class TestClientRequestIdDeduplication:
    """Duplicate submissions with same client_request_id reattach to existing operation."""

    @pytest.mark.unit
    def test_submit_todo_create_accepts_client_request_id_parameter(self) -> None:
        """submit_todo_create method signature includes client_request_id for dedup.

        The existing submit_todo_work already implements dedup via client_request_id.
        The new submit_todo_create must follow the same pattern.
        """
        import inspect

        from teleclaude.core.operations.service import OperationsService

        sig = inspect.signature(OperationsService.submit_todo_create)
        assert "client_request_id" in sig.parameters, (
            "submit_todo_create must accept client_request_id for idempotent submissions"
        )
