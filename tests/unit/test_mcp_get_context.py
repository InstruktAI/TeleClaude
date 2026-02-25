from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.mcp.handlers import MCPHandlersMixin


class DummyHandlers(MCPHandlersMixin):
    def __init__(self):
        self.client = AsyncMock()
        self.computer_name = "local"

    def _is_local_computer(self, computer: str) -> bool:
        return computer == "local"

    async def _get_caller_agent_info(self, caller_session_id: str | None) -> tuple[str | None, str | None]:
        return None, None

    async def _send_remote_request(self, *args: object, **kwargs: object) -> dict[str, str]:
        raise NotImplementedError

    async def _register_listener_if_present(self, target_session_id: str, caller_session_id: str | None = None) -> None:
        _ = target_session_id
        _ = caller_session_id

    def _track_background_task(self, task: object, label: str) -> None:
        _ = task
        _ = label


@pytest.mark.asyncio
async def test_get_context_forwards_projects_and_resolves_user_role() -> None:
    handler = DummyHandlers()
    caller = SimpleNamespace(
        user_role="member", human_role="member", active_agent=None, thinking_mode=None, last_message_sent=None
    )

    with (
        patch("teleclaude.mcp.handlers.db.get_session", new=AsyncMock(return_value=caller)),
        patch("teleclaude.mcp.handlers.build_context_output", return_value="ok") as mock_build,
    ):
        result = await handler.teleclaude__get_context(
            areas=["policy"],
            list_projects=False,
            projects=["teleclaude"],
            caller_session_id="sess-1",
            cwd="/tmp",
        )

    assert result == "ok"
    kwargs = mock_build.call_args.kwargs
    assert kwargs["projects"] == ["teleclaude"]
    assert kwargs["caller_role"] == "member"


@pytest.mark.asyncio
async def test_get_context_defaults_user_role_to_admin_when_session_missing() -> None:
    handler = DummyHandlers()

    with (
        patch("teleclaude.mcp.handlers.db.get_session", new=AsyncMock(return_value=None)),
        patch("teleclaude.mcp.handlers.build_context_output", return_value="ok") as mock_build,
    ):
        result = await handler.teleclaude__get_context(
            areas=[],
            list_projects=True,
            caller_session_id="missing",
            cwd="/tmp",
        )

    assert result == "ok"
    kwargs = mock_build.call_args.kwargs
    assert kwargs["list_projects"] is True
    assert kwargs["caller_role"] == "admin"


@pytest.mark.asyncio
async def test_get_context_allows_non_project_snippet_ids_without_project_root() -> None:
    handler = DummyHandlers()

    with (
        patch("teleclaude.mcp.handlers.db.get_session", new=AsyncMock(return_value=None)),
        patch("teleclaude.mcp.handlers.build_context_output", return_value="ok") as mock_build,
    ):
        result = await handler.teleclaude__get_context(
            snippet_ids=["software-development/policy/commits"],
            caller_session_id="missing",
            cwd="/",
        )

    assert result == "ok"
    assert mock_build.called


@pytest.mark.asyncio
async def test_get_context_allows_cross_project_snippet_ids_without_project_root() -> None:
    handler = DummyHandlers()

    with (
        patch("teleclaude.mcp.handlers.db.get_session", new=AsyncMock(return_value=None)),
        patch("teleclaude.mcp.handlers.build_context_output", return_value="ok") as mock_build,
    ):
        result = await handler.teleclaude__get_context(
            snippet_ids=["teleclaude/design/architecture"],
            caller_session_id="missing",
            cwd="/",
        )

    assert result == "ok"
    assert mock_build.called


@pytest.mark.asyncio
async def test_get_context_requires_project_root_for_project_snippet_ids() -> None:
    handler = DummyHandlers()

    with (
        patch("teleclaude.mcp.handlers.db.get_session", new=AsyncMock(return_value=None)),
        patch("teleclaude.mcp.handlers.build_context_output", return_value="ok") as mock_build,
    ):
        result = await handler.teleclaude__get_context(
            snippet_ids=["project/policy/default"],
            caller_session_id="missing",
            cwd="/",
        )

    assert result.startswith("ERROR: NO_PROJECT_ROOT")
    mock_build.assert_not_called()
