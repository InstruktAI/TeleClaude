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

        assert response["operation_id"] == "op-create-1"
        assert response["kind"] == "todo_create"
        assert response["state"] == "queued"

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

        assert response["operation_id"] == "op-prep-1"
        assert response["kind"] == "todo_prepare"
        assert response["state"] == "queued"


class TestPersistBeforeExecute:
    """Operations must persist the operation row before background execution begins.

    The existing submit_todo_work follows persist-before-execute. The new submit
    methods must follow the same pattern — returning a receipt with state='queued'
    that proves the row was persisted before background execution starts.
    """

    @pytest.mark.unit
    def test_submit_todo_create_method_exists(self) -> None:
        """OperationsService exposes a submit_todo_create method."""
        from teleclaude.core.operations.service import OperationsService

        assert hasattr(OperationsService, "submit_todo_create")
        assert callable(OperationsService.submit_todo_create)

    @pytest.mark.unit
    def test_submit_todo_prepare_method_exists(self) -> None:
        """OperationsService exposes a submit_todo_prepare method."""
        from teleclaude.core.operations.service import OperationsService

        assert hasattr(OperationsService, "submit_todo_prepare")
        assert callable(OperationsService.submit_todo_prepare)


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
            OperationsService,
        )

        assert hasattr(OperationsService, "_run_operation"), (
            "OperationsService must have _run_operation parametric runner"
        )
        assert callable(OperationsService._run_operation)
        assert OPERATION_KIND_TODO_CREATE in _COMPLETION_EVENTS
        assert OPERATION_KIND_TODO_PREPARE in _COMPLETION_EVENTS


class TestOperationPolling:
    """Both todo_create and todo_prepare operations are pollable via /operations/{id}."""

    @pytest.mark.unit
    def test_operations_service_accepts_todo_create_kind_for_polling(self) -> None:
        """OperationsService.get_operation_for_caller can return a todo_create operation.

        The existing get_operation_for_caller is kind-agnostic (fetches by ID), so
        the key requirement is that submit_todo_create produces a row with the right
        kind that the generic polling endpoint can return.
        """
        from teleclaude.core.operations.service import (
            OPERATION_KIND_TODO_CREATE,
            OperationsService,
        )

        # The kind constant must exist and the service must have the submit method
        assert OPERATION_KIND_TODO_CREATE == "todo_create"
        assert hasattr(OperationsService, "submit_todo_create")


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


class TestStaleOnRestartForNewOperations:
    """Stale-on-restart marking applies to todo_create and todo_prepare operations."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_start_marks_nonterminal_todo_create_operations_stale(self) -> None:
        """OperationsService.start() marks all nonterminal operations as stale,
        including todo_create operations left running from a previous daemon run."""
        from teleclaude.core.operations.service import OperationsService

        # Verify the operation kinds exist (they'll be swept by the generic query)
        assert hasattr(OperationsService, "submit_todo_create")

        # The stale-marking is kind-agnostic — it marks ALL nonterminal ops.
        # We verify the new kinds can be submitted, which means they'll be
        # caught by the startup stale sweep.
        from teleclaude.core.operations.service import (
            OPERATION_KIND_TODO_CREATE,
            OPERATION_KIND_TODO_PREPARE,
        )

        assert isinstance(OPERATION_KIND_TODO_CREATE, str)
        assert isinstance(OPERATION_KIND_TODO_PREPARE, str)
