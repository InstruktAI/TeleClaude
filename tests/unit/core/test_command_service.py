"""Characterization tests for teleclaude.core.command_service."""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.constants import JobRole, SlashCommand
from teleclaude.core.command_service import COMMAND_ROLE_MAP, CommandService, _build_widget_summary
from teleclaude.core.models import MessageMetadata
from teleclaude.types.commands import SystemCommand

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _is_direct_session_creation_bypass(node: ast.AST) -> str | None:
    """Return the forbidden core-service call name when a caller bypasses the API edge."""
    if not isinstance(node, ast.Call):
        return None
    if not isinstance(node.func, ast.Attribute):
        return None
    if node.func.attr not in {"run_slash_command", "create_session"}:
        return None
    service_call = node.func.value
    if not isinstance(service_call, ast.Call):
        return None
    service_func = service_call.func
    if isinstance(service_func, ast.Name) and service_func.id == "get_command_service":
        return node.func.attr
    if isinstance(service_func, ast.Attribute) and service_func.attr == "get_command_service":
        return node.func.attr
    return None


def _make_service(*, client: object | None = None) -> CommandService:
    """Build a CommandService with mock dependencies for isolated testing."""
    return CommandService(
        client=client or SimpleNamespace(send_message=AsyncMock(), adapters={}),
        start_polling=AsyncMock(),
        execute_terminal_command=AsyncMock(),
        queue_background_task=MagicMock(),
        bootstrap_session=AsyncMock(),
    )


class TestCommandRoleMap:
    """COMMAND_ROLE_MAP and edge migration tests."""

    @pytest.mark.unit
    def test_next_build_maps_to_worker_builder(self):
        role_info = COMMAND_ROLE_MAP.get(SlashCommand.NEXT_BUILD)
        assert role_info is not None
        _, job_role = role_info
        assert job_role == JobRole.BUILDER

    @pytest.mark.unit
    def test_next_review_build_maps_to_reviewer(self):
        role_info = COMMAND_ROLE_MAP.get(SlashCommand.NEXT_REVIEW_BUILD)
        assert role_info is not None
        _, job_role = role_info
        assert job_role == JobRole.REVIEWER

    @pytest.mark.unit
    def test_next_integrate_maps_to_integrator(self):
        role_info = COMMAND_ROLE_MAP.get(SlashCommand.NEXT_INTEGRATE)
        assert role_info is not None
        _, job_role = role_info
        assert job_role == JobRole.INTEGRATOR

    @pytest.mark.unit
    def test_prepare_v2_commands_use_semantic_worker_roles(self):
        assert COMMAND_ROLE_MAP[SlashCommand.NEXT_PREPARE_INTAKE][1] == JobRole.INTAKER
        assert COMMAND_ROLE_MAP[SlashCommand.NEXT_PREPARE_ARCHITECTURE][1] == JobRole.ARCHITECT
        assert COMMAND_ROLE_MAP[SlashCommand.NEXT_PREPARE_PLAN][1] == JobRole.PLANNER
        assert COMMAND_ROLE_MAP[SlashCommand.NEXT_DRIFT_ANALYZE][1] == JobRole.DRIFT_ANALYZER
        assert COMMAND_ROLE_MAP[SlashCommand.NEXT_EMULATE_PO][1] == JobRole.PO_EMULATOR

    @pytest.mark.unit
    def test_all_entries_have_two_tuple_shape(self):
        for cmd, role_info in COMMAND_ROLE_MAP.items():
            assert len(role_info) == 2, f"Expected 2-tuple for {cmd}"
            system_role, job_role = role_info
            assert isinstance(system_role, str)
            assert isinstance(job_role, JobRole)

    @pytest.mark.unit
    def test_map_is_not_empty(self):
        assert len(COMMAND_ROLE_MAP) > 0

    @pytest.mark.unit
    def test_command_service_no_longer_exposes_run_slash_command(self) -> None:
        """CommandService stops exposing daemon-internal slash-command spawning once callers migrate to HTTP."""
        assert not hasattr(CommandService, "run_slash_command")

    @pytest.mark.unit
    @pytest.mark.timeout(5)
    def test_production_code_contains_no_run_slash_command_ast_references(self) -> None:
        """No production module defines or references run_slash_command after the edge migration."""
        offenders: list[str] = []

        for path in sorted((_REPO_ROOT / "teleclaude").rglob("*.py")):
            if path.name == "__init__.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == "run_slash_command":
                    offenders.append(path.relative_to(_REPO_ROOT).as_posix())
                    break
                if isinstance(node, ast.Attribute) and node.attr == "run_slash_command":
                    offenders.append(path.relative_to(_REPO_ROOT).as_posix())
                    break

        assert not offenders, offenders

    @pytest.mark.unit
    def test_affected_callers_contain_no_direct_session_creation_service_references(self) -> None:
        """Migrated daemon-internal callers stop calling core session services directly."""
        offenders: list[str] = []
        target_paths = (
            "teleclaude/events/cartridges/lifecycle_router.py",
            "teleclaude/hooks/whatsapp_handler.py",
        )

        for relative_path in target_paths:
            path = _REPO_ROOT / relative_path
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                forbidden_call = _is_direct_session_creation_bypass(node)
                if forbidden_call:
                    offenders.append(f"{relative_path}:{forbidden_call}")

        assert not offenders, offenders


class TestBuildWidgetSummary:
    """Widget summary builder tests."""

    @pytest.mark.unit
    def test_builds_summary_with_all_section_types(self) -> None:
        """Widget summary includes title, text, table, code, divider, and footer."""
        data = {
            "title": "Release status",
            "sections": [
                {"type": "text", "label": "Summary", "content": "Everything shipped."},
                {"type": "table", "headers": ["Area", "State"], "rows": [["api", "green"]]},
                {"type": "code", "language": "python", "content": "print('ok')"},
                {"type": "divider"},
            ],
            "footer": "See logs for details.",
        }
        summary = _build_widget_summary(data)
        assert "Release status" in summary
        assert "_Summary_" in summary
        assert "Everything shipped." in summary
        assert "Table: 2 columns, 1 rows" in summary
        assert "Code (python):" in summary
        assert "See logs for details." in summary


class TestSystemCommandHandlers:
    """System command dispatch tests."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_deliver_result_retries_with_plain_text_on_formatting_failure(self) -> None:
        """deliver_result falls back to plain text when formatted send raises."""
        session = SimpleNamespace(session_id="sess-result")
        client = SimpleNamespace(
            send_message=AsyncMock(side_effect=[RuntimeError("formatting failed"), "msg-2"]),
            adapters={},
        )
        service = _make_service(client=client)
        cmd = SystemCommand(
            command="deliver_result",
            session_id="sess-result",
            data={"content": "**ship it**"},
        )

        with patch("teleclaude.core.command_service.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            result = await service.deliver_result(cmd)

        assert isinstance(result, dict)
        assert result["status"] == "success"
        assert result["message_id"] == "msg-2"
        assert "warning" in result
        assert client.send_message.await_count == 2

        first_call, second_call = client.send_message.await_args_list
        assert first_call.kwargs["session"] is session
        assert isinstance(first_call.kwargs["metadata"], MessageMetadata)
        assert first_call.kwargs["metadata"].parse_mode == "MarkdownV2"
        assert first_call.kwargs["ephemeral"] is False

        assert second_call.kwargs["session"] is session
        assert second_call.kwargs["text"] == "**ship it**"
        assert isinstance(second_call.kwargs["metadata"], MessageMetadata)
        assert second_call.kwargs["metadata"].parse_mode is None
        assert second_call.kwargs["ephemeral"] is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_render_widget_sends_markdownified_summary(self) -> None:
        """render_widget builds summary, markdownifies, and sends via adapter."""
        session = SimpleNamespace(session_id="sess-widget")
        client = SimpleNamespace(
            send_message=AsyncMock(),
            adapters={},
        )
        service = _make_service(client=client)
        cmd = SystemCommand(
            command="render_widget",
            session_id="sess-widget",
            data={
                "widget_data": {
                    "title": "Status",
                    "sections": [{"type": "text", "content": "All good."}],
                },
            },
        )

        with (
            patch("teleclaude.core.command_service.db") as mock_db,
            patch(
                "teleclaude.core.command_service.telegramify_markdown",
                return_value="formatted-widget",
            ),
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            result = await service.render_widget(cmd)

        assert isinstance(result, dict)
        assert result["status"] == "success"
        assert isinstance(result["summary"], str)
        client.send_message.assert_awaited_once()
        call = client.send_message.await_args
        assert call.kwargs["text"] == "formatted-widget"
        assert call.kwargs["metadata"].parse_mode == "MarkdownV2"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_escalate_session_raises_without_discord_adapter(self) -> None:
        """Escalation raises ValueError when no DiscordAdapter is present."""
        session = SimpleNamespace(session_id="sess-esc", human_role="customer")
        client = SimpleNamespace(
            send_message=AsyncMock(),
            adapters={"telegram": object()},
        )
        service = _make_service(client=client)
        cmd = SystemCommand(
            command="escalate_session",
            session_id="sess-esc",
            data={"customer_name": "Taylor", "reason": "handoff", "context_summary": ""},
        )

        with patch("teleclaude.core.command_service.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            with pytest.raises(ValueError, match="Discord adapter not available"):
                await service.escalate_session(cmd)
