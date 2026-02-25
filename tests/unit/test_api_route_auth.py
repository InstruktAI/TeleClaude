"""Authorization coverage for protected telec API routes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from teleclaude.api_server import APIServer

JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]


@pytest.fixture
def auth_client() -> TestClient:
    """API client with no auth overrides: protected routes must enforce identity."""
    socket_path = "/tmp/teleclaude-auth-route-test.sock"
    with patch("teleclaude.api_server.get_command_service", return_value=MagicMock()):
        server = APIServer(client=MagicMock(), cache=MagicMock(), socket_path=socket_path)
    return TestClient(server.app)


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("get", "/sessions", None),
        ("post", "/sessions", {"computer": "local", "project_path": "/tmp/project"}),
        ("delete", "/sessions/sess-1?computer=local", None),
        ("post", "/sessions/sess-1/message", {"message": "hello"}),
        ("post", "/sessions/sess-1/keys", {"key": "Enter", "count": 1}),
        (
            "post",
            "/sessions/sess-1/voice",
            {
                "file_path": "/tmp/voice.wav",
                "duration": 1.0,
                "message_id": 1,
                "message_thread_id": 10,
            },
        ),
        (
            "post",
            "/sessions/sess-1/file",
            {"file_path": "/tmp/file.txt", "filename": "file.txt", "caption": "caption", "file_size": 10},
        ),
        ("post", "/sessions/sess-1/agent-restart", None),
        ("post", "/sessions/sess-1/revive", None),
        ("get", "/sessions/sess-1/messages", None),
        ("get", "/computers", None),
        ("get", "/projects", None),
        ("get", "/agents/availability", None),
        ("post", "/sessions/run", {"command": "/next-build", "project": "/tmp/project", "args": "slug-a"}),
        ("post", "/sessions/sess-1/unsubscribe", None),
        ("post", "/sessions/sess-1/result", {"content": "done", "output_format": "markdown"}),
        ("post", "/sessions/sess-1/widget", {"data": {"sections": [{"type": "text", "content": "ok"}]}}),
        (
            "post",
            "/sessions/sess-1/escalate",
            {"customer_name": "Jane Doe", "reason": "Need admin help", "context_summary": "summary"},
        ),
        ("post", "/agents/claude/status", {"status": "degraded", "reason": "rate_limited"}),
        ("post", "/deploy", {"computers": ["peer-1"]}),
    ],
)
def test_protected_routes_require_identity(
    auth_client: TestClient, method: str, path: str, json_body: dict[str, JsonValue] | None
) -> None:
    if json_body is None:
        response = auth_client.request(method, path)
    else:
        response = auth_client.request(method, path, json=json_body)
    assert response.status_code == 401


def test_channels_routes_require_identity(auth_client: TestClient) -> None:
    list_response = auth_client.get("/api/channels/")
    publish_response = auth_client.post("/api/channels/test-channel/publish", json={"payload": {"k": "v"}})
    assert list_response.status_code == 401
    assert publish_response.status_code == 401


def test_identity_headers_rejected_from_untrusted_source(auth_client: TestClient) -> None:
    response = auth_client.get(
        "/sessions",
        headers={
            "x-web-user-email": "admin@example.com",
            "x-web-user-role": "admin",
        },
    )
    assert response.status_code == 403
