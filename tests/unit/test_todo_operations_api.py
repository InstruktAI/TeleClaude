"""Receipt-first API coverage for long-running todo work operations."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from teleclaude.api.auth import CallerIdentity, verify_caller
from teleclaude.api_server import APIServer


def _install_auth_override(client: TestClient) -> None:
    async def _fake_verify_caller() -> CallerIdentity:
        return CallerIdentity(
            session_id="owner-session",
            system_role=None,
            human_role="admin",
            tmux_session_name="tc_test",
        )

    client.app.dependency_overrides[verify_caller] = _fake_verify_caller


def _make_client() -> TestClient:
    socket_path = f"/tmp/teleclaude-op-api-{uuid.uuid4().hex}.sock"
    with patch("teleclaude.api_server.get_command_service", return_value=MagicMock()):
        server = APIServer(client=MagicMock(), cache=MagicMock(), socket_path=socket_path)
    client = TestClient(server.app)
    _install_auth_override(client)
    return client


def test_todo_work_returns_operation_receipt_without_waiting_for_next_work() -> None:
    client = _make_client()
    service = MagicMock()
    service.submit_todo_work = AsyncMock(
        return_value={
            "operation_id": "op-123",
            "kind": "todo_work",
            "state": "queued",
            "poll_after_ms": 250,
            "status_path": "/operations/op-123",
            "recovery_command": "telec operations get op-123",
        }
    )

    with (
        patch("teleclaude.api.todo_routes.get_operations_service", return_value=service),
        patch("teleclaude.api.todo_routes.next_work", new_callable=AsyncMock) as next_work,
    ):
        response = client.post(
            "/todos/work",
            json={
                "slug": "async-operation-receipts",
                "cwd": "/tmp/project",
                "client_request_id": "req-123",
            },
        )

    assert response.status_code == 202
    assert response.json() == {
        "operation_id": "op-123",
        "kind": "todo_work",
        "state": "queued",
        "poll_after_ms": 250,
        "status_path": "/operations/op-123",
        "recovery_command": "telec operations get op-123",
    }
    service.submit_todo_work.assert_awaited_once_with(
        slug="async-operation-receipts",
        cwd="/tmp/project",
        caller_session_id="owner-session",
        client_request_id="req-123",
    )
    next_work.assert_not_awaited()


def test_get_operation_returns_status_payload() -> None:
    client = _make_client()
    service = MagicMock()
    service.get_operation_for_caller = AsyncMock(
        return_value={
            "operation_id": "op-123",
            "kind": "todo_work",
            "state": "running",
            "poll_after_ms": 250,
            "status_path": "/operations/op-123",
            "recovery_command": "telec operations get op-123",
            "progress_phase": "dispatch_decision",
        }
    )

    with patch("teleclaude.api.operations_routes.get_operations_service", return_value=service):
        response = client.get("/operations/op-123")

    assert response.status_code == 200
    assert response.json()["operation_id"] == "op-123"
    assert response.json()["state"] == "running"
    service.get_operation_for_caller.assert_awaited_once_with(
        operation_id="op-123",
        caller_session_id="owner-session",
        human_role="admin",
    )
