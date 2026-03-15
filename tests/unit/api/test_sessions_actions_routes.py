"""Characterization tests for session action routes."""

from __future__ import annotations

import shlex
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from teleclaude.api import sessions_actions_routes
from teleclaude.api.auth import CallerIdentity
from teleclaude.api_models import (
    EscalateRequest,
    FileUploadRequest,
    KeysRequest,
    RenderWidgetRequest,
    RunSessionRequest,
    SendResultRequest,
    VoiceInputRequest,
)
from teleclaude.core.models import MessageMetadata
from teleclaude.core.origins import InputOrigin
from teleclaude.types.commands import GetSessionDataCommand


def _identity(
    session_id: str,
    *,
    human_role: str | None = None,
    principal: str | None = None,
) -> CallerIdentity:
    return CallerIdentity(
        session_id=session_id,
        system_role=None,
        human_role=human_role,
        tmux_session_name=None,
        principal=principal,
    )


class TestSessionsActionsRoutes:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_keys_success_wires_command_mapper_and_service(self) -> None:
        """Send keys builds the mapped command and forwards it to the command service."""
        http_request = SimpleNamespace(headers={})
        request = KeysRequest(key="Enter", count=3)
        identity = _identity("sess-keys")
        mapped_command = object()
        service = SimpleNamespace(keys=AsyncMock())

        with (
            patch("teleclaude.api.session_access.check_session_access", new=AsyncMock()) as check_session_access,
            patch.object(
                sessions_actions_routes.CommandMapper,
                "map_api_input",
                return_value=mapped_command,
            ) as map_api_input,
            patch.object(sessions_actions_routes, "get_command_service", return_value=service),
        ):
            response = await sessions_actions_routes.send_keys_endpoint(
                http_request,
                "sess-keys",
                request,
                identity=identity,
            )

        assert response == {"status": "success"}
        check_session_access.assert_awaited_once_with(http_request, "sess-keys")
        service.keys.assert_awaited_once_with(mapped_command)

        command_name, payload, metadata = map_api_input.call_args.args
        assert command_name == "keys"
        assert payload == {"session_id": "sess-keys", "key": "Enter", "args": ["3"]}
        assert isinstance(metadata, MessageMetadata)
        assert metadata.origin == InputOrigin.API.value

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_voice_success_wires_request_payload_to_voice_handler(self) -> None:
        """Voice input maps request fields to the voice handler command."""
        http_request = SimpleNamespace(headers={})
        request = VoiceInputRequest(
            file_path="/tmp/input.ogg",
            duration=2.5,
            message_id="voice-1",
            message_thread_id=77,
        )
        identity = _identity("sess-voice")
        mapped_command = object()
        service = SimpleNamespace(handle_voice=AsyncMock())

        with (
            patch("teleclaude.api.session_access.check_session_access", new=AsyncMock()) as check_session_access,
            patch.object(
                sessions_actions_routes.CommandMapper,
                "map_api_input",
                return_value=mapped_command,
            ) as map_api_input,
            patch.object(sessions_actions_routes, "get_command_service", return_value=service),
        ):
            response = await sessions_actions_routes.send_voice_endpoint(
                http_request,
                "sess-voice",
                request,
                identity=identity,
            )

        assert response == {"status": "success"}
        check_session_access.assert_awaited_once_with(http_request, "sess-voice")
        service.handle_voice.assert_awaited_once_with(mapped_command)

        command_name, payload, metadata = map_api_input.call_args.args
        assert command_name == "handle_voice"
        assert payload == {
            "session_id": "sess-voice",
            "file_path": "/tmp/input.ogg",
            "duration": 2.5,
            "message_id": "voice-1",
            "message_thread_id": 77,
        }
        assert isinstance(metadata, MessageMetadata)
        assert metadata.origin == InputOrigin.API.value

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_file_success_uses_caller_session_identity(self) -> None:
        """File uploads always target the caller's own session."""
        request = FileUploadRequest(
            file_path="/tmp/report.txt",
            filename="report.txt",
            caption="Quarterly report",
            file_size=512,
        )
        identity = _identity("sess-file")
        mapped_command = object()
        service = SimpleNamespace(handle_file=AsyncMock())

        with (
            patch.object(
                sessions_actions_routes.CommandMapper,
                "map_api_input",
                return_value=mapped_command,
            ) as map_api_input,
            patch.object(sessions_actions_routes, "get_command_service", return_value=service),
        ):
            response = await sessions_actions_routes.send_file_endpoint(request, identity=identity)

        assert response == {"status": "success"}
        service.handle_file.assert_awaited_once_with(mapped_command)

        command_name, payload, metadata = map_api_input.call_args.args
        assert command_name == "handle_file"
        assert payload == {
            "session_id": "sess-file",
            "file_path": "/tmp/report.txt",
            "filename": "report.txt",
            "caption": "Quarterly report",
            "file_size": 512,
        }
        assert isinstance(metadata, MessageMetadata)
        assert metadata.origin == InputOrigin.API.value

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_agent_restart_returns_409_when_session_has_no_active_agent(self) -> None:
        """Agent restart rejects sessions that have not started an agent yet."""
        http_request = SimpleNamespace(headers={})
        identity = _identity("sess-restart")
        service = SimpleNamespace(restart_agent=AsyncMock())

        with (
            patch("teleclaude.api.session_access.check_session_access", new=AsyncMock()) as check_session_access,
            patch.object(sessions_actions_routes, "db") as db,
            patch.object(sessions_actions_routes.CommandMapper, "map_api_input") as map_api_input,
            patch.object(sessions_actions_routes, "get_command_service", return_value=service),
        ):
            db.get_session = AsyncMock(return_value=SimpleNamespace(active_agent=None, native_session_id="native-123"))

            with pytest.raises(HTTPException) as exc_info:
                await sessions_actions_routes.agent_restart(http_request, "sess-restart", identity=identity)

        assert exc_info.value.status_code == 409
        check_session_access.assert_awaited_once_with(http_request, "sess-restart")
        db.get_session.assert_awaited_once_with("sess-restart")
        map_api_input.assert_not_called()
        service.restart_agent.assert_not_awaited()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_revive_session_resolves_native_session_ids_before_restart(self) -> None:
        """Revive accepts a native agent session ID and restarts the mapped TeleClaude session."""
        http_request = SimpleNamespace(headers={})
        identity = _identity("caller-1")
        mapped_command = object()
        service = SimpleNamespace(restart_agent=AsyncMock(return_value=(True, None)))

        resolved_session = SimpleNamespace(session_id="sess-revive", active_agent="claude")
        current_session = SimpleNamespace(active_agent="claude", native_session_id="native-7")
        refreshed_session = SimpleNamespace(tmux_session_name="tmux-revive")

        with (
            patch("teleclaude.api.session_access.check_session_access", new=AsyncMock()) as check_session_access,
            patch.object(sessions_actions_routes, "db") as db,
            patch.object(
                sessions_actions_routes.CommandMapper,
                "map_api_input",
                return_value=mapped_command,
            ) as map_api_input,
            patch.object(sessions_actions_routes, "get_command_service", return_value=service),
            patch.object(sessions_actions_routes, "get_known_agents", return_value=["claude", "codex", "gemini"]),
        ):
            db.get_session_by_field = AsyncMock(return_value=resolved_session)
            db.get_session = AsyncMock(side_effect=[current_session, refreshed_session])

            response = await sessions_actions_routes.revive_session(
                http_request,
                "native-7",
                agent="claude",
                identity=identity,
            )

        assert response.status == "success"
        assert response.session_id == "sess-revive"
        assert response.tmux_session_name == "tmux-revive"
        assert response.agent == "claude"
        db.get_session_by_field.assert_awaited_once_with("native_session_id", "native-7", include_initializing=True)
        check_session_access.assert_awaited_once_with(http_request, "sess-revive")
        service.restart_agent.assert_awaited_once_with(mapped_command)

        command_name, payload, metadata = map_api_input.call_args.args
        assert command_name == "agent_restart"
        assert payload == {"session_id": "sess-revive", "args": []}
        assert isinstance(metadata, MessageMetadata)
        assert metadata.origin == InputOrigin.API.value

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_session_messages_projects_structured_transcripts_with_query_flags(self) -> None:
        """Structured transcript reads honor the visibility flags from query parameters."""
        http_request = SimpleNamespace(headers={})
        identity = _identity("sess-messages")
        session = SimpleNamespace(
            active_agent="claude",
            transcript_files='["/tmp/previous.jsonl"]',
            native_log_file="/tmp/current.jsonl",
        )
        projected_block = object()
        structured_message = SimpleNamespace(
            role="assistant",
            type="text",
            text="All set",
            timestamp="2025-02-01T00:00:00Z",
            entry_index=4,
            file_index=1,
        )

        with (
            patch("teleclaude.api.session_access.check_session_access", new=AsyncMock()) as check_session_access,
            patch.object(sessions_actions_routes, "db") as db,
            patch("teleclaude.core.agents.resolve_parser_agent", return_value="claude") as resolve_parser_agent,
            patch(
                "teleclaude.output_projection.conversation_projector.project_conversation_chain",
                return_value=[projected_block],
            ) as project_conversation_chain,
            patch(
                "teleclaude.output_projection.serializers.to_structured_message",
                return_value=structured_message,
            ) as to_structured_message,
        ):
            db.get_session = AsyncMock(return_value=session)

            response = await sessions_actions_routes.get_session_messages(
                http_request,
                "sess-messages",
                since="2025-02-01T00:00:00Z",
                include_tools=True,
                include_thinking=True,
                tail_chars=321,
                identity=identity,
            )

        assert response.session_id == "sess-messages"
        assert response.agent == "claude"
        assert [message.model_dump() for message in response.messages] == [
            {
                "role": "assistant",
                "type": "text",
                "text": "All set",
                "timestamp": "2025-02-01T00:00:00Z",
                "entry_index": 4,
                "file_index": 1,
            }
        ]
        check_session_access.assert_awaited_once_with(http_request, "sess-messages")
        resolve_parser_agent.assert_called_once_with("claude")
        to_structured_message.assert_called_once_with(projected_block)

        chain, agent_name, policy = project_conversation_chain.call_args.args
        assert chain == ["/tmp/previous.jsonl", "/tmp/current.jsonl"]
        assert agent_name == "claude"
        assert policy.include_tools is True
        assert policy.include_tool_results is True
        assert policy.include_thinking is True
        assert project_conversation_chain.call_args.kwargs["since"] == "2025-02-01T00:00:00Z"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_session_messages_falls_back_to_tail_output_when_projection_is_empty(self) -> None:
        """Fallback session data becomes a single assistant text message when no structured output exists."""
        http_request = SimpleNamespace(headers={})
        identity = _identity("sess-tail")
        session = SimpleNamespace(active_agent="claude", transcript_files="[]", native_log_file=None)
        service = SimpleNamespace(get_session_data=AsyncMock(return_value={"messages": "terminal tail output"}))

        with (
            patch("teleclaude.api.session_access.check_session_access", new=AsyncMock()) as check_session_access,
            patch.object(sessions_actions_routes, "db") as db,
            patch.object(sessions_actions_routes, "get_command_service", return_value=service),
        ):
            db.get_session = AsyncMock(return_value=session)

            response = await sessions_actions_routes.get_session_messages(
                http_request,
                "sess-tail",
                since="2025-02-01T00:00:00Z",
                include_tools=False,
                include_thinking=False,
                tail_chars=0,
                identity=identity,
            )

        assert response.session_id == "sess-tail"
        assert response.agent == "claude"
        assert [message.model_dump() for message in response.messages] == [
            {
                "role": "assistant",
                "type": "text",
                "text": "terminal tail output",
                "timestamp": None,
                "entry_index": 0,
                "file_index": 0,
            }
        ]
        check_session_access.assert_awaited_once_with(http_request, "sess-tail")
        service.get_session_data.assert_awaited_once()

        command = service.get_session_data.await_args.args[0]
        assert isinstance(command, GetSessionDataCommand)
        assert command.session_id == "sess-tail"
        assert command.since_timestamp == "2025-02-01T00:00:00Z"
        assert command.tail_chars == 10000

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_run_session_builds_worker_metadata_for_lifecycle_commands(self) -> None:
        """Worker lifecycle commands carry initiator and slug metadata into the new session request."""
        request = RunSessionRequest(
            command="/next-review-build",
            args="chartest-api-routes --direct",
            project="/repo/demo",
            agent="codex",
            subfolder="api",
            thinking_mode="med",
            detach=True,
            additional_context="Trace real route behavior.",
        )
        identity = _identity("caller-123", human_role="member", principal="human:member@example.com")
        mapped_command = object()
        service = SimpleNamespace(
            create_session=AsyncMock(return_value={"session_id": "sess-run", "tmux_session_name": "tmux-run"})
        )

        with (
            patch.object(sessions_actions_routes, "assert_agent_enabled", return_value="codex") as assert_agent_enabled,
            patch.object(sessions_actions_routes, "get_default_agent") as get_default_agent,
            patch.object(
                sessions_actions_routes.CommandMapper,
                "map_api_input",
                return_value=mapped_command,
            ) as map_api_input,
            patch.object(sessions_actions_routes, "get_command_service", return_value=service),
        ):
            response = await sessions_actions_routes.run_session(request, identity=identity)

        assert response.status == "success"
        assert response.session_id == "sess-run"
        assert response.tmux_session_name == "tmux-run"
        assert response.agent == "codex"
        assert_agent_enabled.assert_called_once_with("codex")
        get_default_agent.assert_not_called()
        service.create_session.assert_awaited_once_with(mapped_command)

        command_name, payload, metadata = map_api_input.call_args.args
        expected_title = (
            "/next-review-build chartest-api-routes --direct\n\nADDITIONAL CONTEXT:\nTrace real route behavior."
        )
        expected_role = sessions_actions_routes.COMMAND_ROLE_MAP[sessions_actions_routes.SlashCommand.NEXT_REVIEW_BUILD]
        assert command_name == "new_session"
        assert payload == {"skip_listener_registration": True}
        assert isinstance(metadata, MessageMetadata)
        assert metadata.origin == InputOrigin.API.value
        assert metadata.title == expected_title
        assert metadata.project_path == "/repo/demo"
        assert metadata.subdir == "api"
        assert metadata.channel_metadata == {
            "initiator_session_id": "caller-123",
            "working_slug": "chartest-api-routes",
        }
        assert metadata.auto_command == f"agent_then_message codex med {shlex.quote(expected_title)}"
        assert metadata.session_metadata is not None
        assert metadata.session_metadata.system_role == expected_role[0]
        assert metadata.session_metadata.job == expected_role[1].value
        assert metadata.session_metadata.human_role == "member"
        assert metadata.session_metadata.principal == "human:member@example.com"

    @pytest.mark.unit
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("unregister_result", "expected_status"),
        [(True, "success"), (False, "error")],
    )
    async def test_unsubscribe_session_reports_listener_state(
        self,
        unregister_result: bool,
        expected_status: str,
    ) -> None:
        """Unsubscribe reports whether the caller had an active listener on the target session."""
        identity = _identity("caller-unsub")

        with patch(
            "teleclaude.core.session_listeners.unregister_listener",
            new=AsyncMock(return_value=unregister_result),
        ) as unregister_listener:
            response = await sessions_actions_routes.unsubscribe_session("sess-unsub", identity=identity)

        message = response["message"]
        assert response["status"] == expected_status
        assert isinstance(message, str)
        assert message
        assert "sess-unsub" in message
        unregister_listener.assert_awaited_once_with(
            target_session_id="sess-unsub",
            caller_session_id="caller-unsub",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_result_retries_with_plain_text_after_formatted_send_failure(self) -> None:
        """Result delivery falls back to plain text when formatted output send fails."""
        identity = _identity("sess-result")
        request = SendResultRequest(content="**ship it**")
        session = SimpleNamespace(session_id="sess-result")
        client = SimpleNamespace(send_message=AsyncMock(side_effect=[RuntimeError("formatting failed"), "msg-2"]))
        fake_markdown = ModuleType("teleclaude.utils.markdown")
        fake_markdown.telegramify_markdown = MagicMock(return_value="formatted-body")

        with (
            patch.object(sessions_actions_routes, "_client", client),
            patch.object(sessions_actions_routes, "db") as db,
            patch.dict("sys.modules", {"teleclaude.utils.markdown": fake_markdown}),
        ):
            db.get_session = AsyncMock(return_value=session)

            response = await sessions_actions_routes.send_result_endpoint(request, identity=identity)

        assert response["status"] == "success"
        assert response["message_id"] == "msg-2"
        assert set(response) == {"status", "message_id", "warning"}
        db.get_session.assert_awaited_once_with("sess-result")
        fake_markdown.telegramify_markdown.assert_called_once_with(request.content)
        assert client.send_message.await_count == 2

        first_call, second_call = client.send_message.await_args_list
        assert first_call.kwargs["session"] is session
        assert first_call.kwargs["text"] == fake_markdown.telegramify_markdown.return_value
        assert isinstance(first_call.kwargs["metadata"], MessageMetadata)
        assert first_call.kwargs["metadata"].parse_mode == "MarkdownV2"
        assert first_call.kwargs["ephemeral"] is False

        assert second_call.kwargs["session"] is session
        assert second_call.kwargs["text"] == request.content
        assert isinstance(second_call.kwargs["metadata"], MessageMetadata)
        assert second_call.kwargs["metadata"].parse_mode is None
        assert second_call.kwargs["ephemeral"] is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_render_widget_endpoint_summarizes_sections_before_delivery(self) -> None:
        """Widget rendering returns the generated summary and sends its markdownified form."""
        request = RenderWidgetRequest(
            data={
                "title": "Release status",
                "sections": [
                    {"type": "text", "label": "Summary", "content": "Everything shipped."},
                    {"type": "table", "headers": ["Area", "State"], "rows": [["api", "green"]]},
                    {"type": "code", "language": "python", "content": "print('ok')"},
                    {"type": "divider"},
                ],
                "footer": "See logs for details.",
            }
        )
        identity = _identity("sess-widget")
        session = SimpleNamespace(session_id="sess-widget")
        client = SimpleNamespace(send_message=AsyncMock())
        fake_markdown = ModuleType("teleclaude.utils.markdown")
        fake_markdown.telegramify_markdown = MagicMock(return_value="widget-body")

        with (
            patch.object(sessions_actions_routes, "_client", client),
            patch.object(sessions_actions_routes, "db") as db,
            patch.dict("sys.modules", {"teleclaude.utils.markdown": fake_markdown}),
        ):
            db.get_session = AsyncMock(return_value=session)

            response = await sessions_actions_routes.render_widget_endpoint(request, identity=identity)

        summary = response["summary"]
        assert response["status"] == "success"
        assert isinstance(summary, str)
        assert "Release status" in summary
        assert "_Summary_" in summary
        assert "Everything shipped." in summary
        assert "Table: 2 columns, 1 rows" in summary
        assert "Code (python):" in summary
        assert "See logs for details." in summary
        db.get_session.assert_awaited_once_with("sess-widget")
        fake_markdown.telegramify_markdown.assert_called_once_with(summary)
        client.send_message.assert_awaited_once()

        send_call = client.send_message.await_args
        assert send_call.kwargs["session"] is session
        assert send_call.kwargs["text"] == "widget-body"
        assert send_call.kwargs["ephemeral"] is False
        assert isinstance(send_call.kwargs["metadata"], MessageMetadata)
        assert send_call.kwargs["metadata"].parse_mode == "MarkdownV2"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_escalate_session_returns_503_without_discord_adapter(self) -> None:
        """Escalation requires a Discord adapter even when the session is otherwise eligible."""
        request = EscalateRequest(customer_name="Taylor", reason="handoff")
        identity = _identity("sess-escalate", human_role="customer")
        fake_discord_module = ModuleType("teleclaude.adapters.discord_adapter")
        fake_discord_module.DiscordAdapter = type("DiscordAdapter", (), {})
        client = SimpleNamespace(adapters={"telegram": object()})

        with (
            patch.object(sessions_actions_routes, "_client", client),
            patch.object(sessions_actions_routes, "db") as db,
            patch.dict("sys.modules", {"teleclaude.adapters.discord_adapter": fake_discord_module}),
        ):
            db.get_session = AsyncMock(return_value=SimpleNamespace(human_role="customer"))
            db.update_session = AsyncMock()

            with pytest.raises(HTTPException) as exc_info:
                await sessions_actions_routes.escalate_session(request, identity=identity)

        assert exc_info.value.status_code == 503
        db.get_session.assert_awaited_once_with("sess-escalate")
        db.update_session.assert_not_awaited()
