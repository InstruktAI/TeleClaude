"""Characterization tests for operation status routes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.api import operations_routes
from teleclaude.core.operations.service import SerializedOperation


class TestOperationsRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_operation_scopes_lookup_to_caller_identity(self) -> None:
        """Operation lookup passes caller identity fields through to the service layer."""
        payload: SerializedOperation = {
            "operation_id": "op-123",
            "kind": "todo_work",
            "state": "queued",
            "poll_after_ms": 250,
            "status_path": "/operations/op-123",
            "recovery_command": "telec todo work chartest-api-routes",
        }
        service = MagicMock()
        service.get_operation_for_caller = AsyncMock(return_value=payload)
        identity = SimpleNamespace(session_id="sess-123", human_role="member")

        with patch("teleclaude.api.operations_routes.get_operations_service", return_value=service):
            result = await operations_routes.get_operation("op-123", identity=identity)

        assert result == payload
        service.get_operation_for_caller.assert_awaited_once_with(
            operation_id="op-123",
            caller_session_id="sess-123",
            human_role="member",
        )
