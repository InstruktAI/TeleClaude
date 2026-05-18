"""Characterization tests for session action routes."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from teleclaude.api import sessions_actions_routes
from teleclaude.api.auth import CallerIdentity
from teleclaude.api.sessions_actions_routes import SessionMessagesQuery
from teleclaude.api_models import (
    EscalateRequest,
    FileUploadRequest,
    KeysRequest,
    RenderWidgetRequest,
    RunSessionRequest,
    SendResultRequest,
    VoiceInputRequest,
)
from teleclaude.constants import ROLE_INTEGRATOR, ROLE_ORCHESTRATOR, ROLE_WORKER, JobRole
from teleclaude.core.models import MessageMetadata, Session, SessionLaunchKind
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


def _system_identity(
    session_id: str,
    *,
    system_role: str,
    human_role: str | None = "admin",
) -> CallerIdentity:
    return CallerIdentity(
        session_id=session_id,
        system_role=system_role,
        human_role=human_role,
        tmux_session_name=None,
    )


class TestSessionsActionsRoutes:
    """Session action route dispatch and role assignment tests."""

    def _make_session(self, **kwargs: object) -> Session:
        defaults = {
            "session_id": "sess-messages",
            "computer_name": "local",
            "tmux_session_name": "tc-sess-messages",
            "title": "Messages",
        }
        defaults.update(kwargs)
        return Session(**defaults)

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
            patch(
                "teleclaude.api.sessions_actions_routes.check_session_access", new=AsyncMock()
            ) as check_session_access,
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
                _identity=identity,
            )

        assert response == {"status": "success"}
        check_session_access.assert_awaited_once_with(http_request, "sess-keys")
        service.keys.assert_awaited_once_with(mapped_command)

        command_name, payload, metadata = map_api_input.call_args.args
        assert command_name == "keys"
        assert payload == {"session_id": "sess-keys", "key": "Enter", "args": ["3"]}
        assert isinstance(metadata, MessageMetadata)
        assert metadata.origin == InputOrigin.TERMINAL.value

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
            patch(
                "teleclaude.api.sessions_actions_routes.check_session_access", new=AsyncMock()
            ) as check_session_access,
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
                _identity=identity,
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
        assert metadata.origin == InputOrigin.TERMINAL.value

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
        assert metadata.origin == InputOrigin.TERMINAL.value

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_agent_restart_returns_409_when_session_has_no_active_agent(self) -> None:
        """Agent restart rejects sessions that have not started an agent yet."""
        http_request = SimpleNamespace(headers={})
        identity = _identity("sess-restart")
        service = SimpleNamespace(restart_agent=AsyncMock())

        with (
            patch(
                "teleclaude.api.sessions_actions_routes.check_session_access", new=AsyncMock()
            ) as check_session_access,
            patch.object(sessions_actions_routes, "db") as db,
            patch.object(sessions_actions_routes.CommandMapper, "map_api_input") as map_api_input,
            patch.object(sessions_actions_routes, "get_command_service", return_value=service),
        ):
            db.get_session = AsyncMock(return_value=SimpleNamespace(active_agent=None, native_session_id="native-123"))

            with pytest.raises(HTTPException) as exc_info:
                await sessions_actions_routes.agent_restart(http_request, "sess-restart", _identity=identity)

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
            patch(
                "teleclaude.api.sessions_actions_routes.check_session_access", new=AsyncMock()
            ) as check_session_access,
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
        assert metadata.origin == InputOrigin.TERMINAL.value

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_revive_session_rejects_unknown_codex_native_session_id(self) -> None:
        """Revive rejects Codex native session IDs that do not resolve to a transcript."""
        http_request = SimpleNamespace(headers={}, query_params={})
        identity = _identity("caller-1")
        service = SimpleNamespace(
            create_session=AsyncMock(),
            restart_agent=AsyncMock(return_value=(True, None)),
        )
        current_session = SimpleNamespace(
            active_agent="codex",
            native_session_id="teleclaude-uuid-not-codex",
        )
        refreshed_session = SimpleNamespace(tmux_session_name="tmux-revive")

        with (
            patch(
                "teleclaude.api.sessions_actions_routes.check_session_access", new=AsyncMock()
            ) as check_session_access,
            patch.object(sessions_actions_routes, "db") as db,
            patch.object(sessions_actions_routes.CommandMapper, "map_api_input") as map_api_input,
            patch.object(sessions_actions_routes, "get_command_service", return_value=service) as get_command_service,
            patch.object(
                sessions_actions_routes,
                "discover_codex_transcript_path",
                return_value=None,
            ) as discover_codex_transcript_path,
            patch.object(sessions_actions_routes, "get_known_agents", return_value=["claude", "codex", "gemini"]),
        ):
            db.get_session_by_field = AsyncMock(return_value=None)
            db.get_session = AsyncMock(side_effect=[current_session, refreshed_session])

            with pytest.raises(HTTPException) as exc_info:
                await sessions_actions_routes.revive_session(
                    http_request,
                    "teleclaude-uuid-not-codex",
                    agent="codex",
                    identity=identity,
                )

        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Native session ID is not valid for agent 'codex'"
        db.get_session_by_field.assert_awaited_once_with(
            "native_session_id",
            "teleclaude-uuid-not-codex",
            include_initializing=True,
        )
        discover_codex_transcript_path.assert_called_once_with("teleclaude-uuid-not-codex")
        check_session_access.assert_not_awaited()
        map_api_input.assert_not_called()
        get_command_service.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_revive_session_rejects_unknown_claude_native_session_id(self) -> None:
        """Revive rejects Claude native session IDs that do not match discovered transcripts."""
        http_request = SimpleNamespace(headers={}, query_params={})
        identity = _identity("caller-1")
        transcript = SimpleNamespace(path=Path("/tmp/claude-session.jsonl"))

        with (
            patch(
                "teleclaude.api.sessions_actions_routes.check_session_access", new=AsyncMock()
            ) as check_session_access,
            patch.object(sessions_actions_routes, "db") as db,
            patch.object(sessions_actions_routes.CommandMapper, "map_api_input") as map_api_input,
            patch.object(sessions_actions_routes, "get_command_service") as get_command_service,
            patch.object(
                sessions_actions_routes, "discover_transcripts", return_value=[transcript]
            ) as discover_transcripts,
            patch.object(
                sessions_actions_routes, "extract_session_id", return_value="other-native-id"
            ) as extract_session_id,
        ):
            db.get_session_by_field = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await sessions_actions_routes.revive_session(
                    http_request,
                    "missing-claude-native-id",
                    agent="claude",
                    identity=identity,
                )

        assert exc_info.value.status_code == 404
        db.get_session_by_field.assert_awaited_once_with(
            "native_session_id",
            "missing-claude-native-id",
            include_initializing=True,
        )
        discover_transcripts.assert_called_once()
        extract_session_id.assert_called_once_with(
            transcript.path, sessions_actions_routes.agents_module.AgentName.CLAUDE
        )
        check_session_access.assert_not_awaited()
        map_api_input.assert_not_called()
        get_command_service.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_revive_session_rejects_unknown_agent_name(self) -> None:
        """Revive treats unknown agent names as invalid native-session lookups."""
        http_request = SimpleNamespace(headers={}, query_params={})
        identity = _identity("caller-1")

        with (
            patch(
                "teleclaude.api.sessions_actions_routes.check_session_access", new=AsyncMock()
            ) as check_session_access,
            patch.object(sessions_actions_routes, "db") as db,
            patch.object(sessions_actions_routes.CommandMapper, "map_api_input") as map_api_input,
            patch.object(sessions_actions_routes, "get_command_service") as get_command_service,
        ):
            db.get_session_by_field = AsyncMock(return_value=None)

            with pytest.raises(HTTPException) as exc_info:
                await sessions_actions_routes.revive_session(
                    http_request,
                    "native-id",
                    agent="bogus",
                    identity=identity,
                )

        assert exc_info.value.status_code == 404
        db.get_session_by_field.assert_awaited_once_with("native_session_id", "native-id", include_initializing=True)
        check_session_access.assert_not_awaited()
        map_api_input.assert_not_called()
        get_command_service.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_session_messages_projects_structured_transcripts_with_query_flags(self) -> None:
        """Structured transcript reads honor the visibility flags from query parameters."""
        http_request = SimpleNamespace(headers={})
        identity = _identity("sess-messages")
        session = self._make_session(
            active_agent="claude",
            transcript_files='["/tmp/previous.jsonl"]',
            native_log_file="/tmp/current.jsonl",
            last_activity=datetime(2025, 2, 1, 12, 0, 3, tzinfo=UTC),
            last_message_sent_at=datetime(2025, 2, 1, 12, 0, 5, tzinfo=UTC),
            last_agent_stop_at=datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC),
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
            patch(
                "teleclaude.api.sessions_actions_routes.check_session_access", new=AsyncMock()
            ) as check_session_access,
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
                query=SessionMessagesQuery(
                    since="2025-02-01T00:00:00Z",
                    include_tools=True,
                    include_thinking=True,
                    tail_chars=321,
                ),
                _identity=identity,
            )

        assert response.session_id == "sess-messages"
        assert response.agent == "claude"
        assert response.last_input_at == "2025-02-01T12:00:05+00:00"
        assert response.last_agent_stop_at == "2025-02-01T12:00:00+00:00"
        assert response.last_activity == "2025-02-01T12:00:03+00:00"
        assert response.agent_status == "active"
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
    async def test_get_session_messages_sets_active_status_when_activity_exists_before_stop(self) -> None:
        """Recorded activity means active until the stop event becomes the latest activity."""
        http_request = SimpleNamespace(headers={})
        identity = _identity("sess-active")
        session = self._make_session(
            session_id="sess-active",
            active_agent="claude",
            transcript_files="[]",
            native_log_file=None,
            last_activity=datetime(2025, 2, 1, 12, 0, 3, tzinfo=UTC),
            last_agent_stop_at=None,
        )
        service = SimpleNamespace(get_session_data=AsyncMock(return_value={"messages": "terminal tail output"}))

        with (
            patch(
                "teleclaude.api.sessions_actions_routes.check_session_access", new=AsyncMock()
            ) as check_session_access,
            patch.object(sessions_actions_routes, "db") as db,
            patch.object(sessions_actions_routes, "get_command_service", return_value=service),
        ):
            db.get_session = AsyncMock(return_value=session)

            response = await sessions_actions_routes.get_session_messages(
                http_request,
                "sess-active",
                query=SessionMessagesQuery(),
                _identity=identity,
            )

        assert response.agent_status == "active"
        assert response.last_activity == "2025-02-01T12:00:03+00:00"
        assert response.last_agent_stop_at is None
        check_session_access.assert_awaited_once_with(http_request, "sess-active")
        service.get_session_data.assert_awaited_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_session_messages_falls_back_to_tail_output_when_projection_is_empty(self) -> None:
        """Fallback session data becomes a single assistant text message when no structured output exists."""
        http_request = SimpleNamespace(headers={})
        identity = _identity("sess-tail")
        last_stop = datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)
        session = self._make_session(
            session_id="sess-tail",
            active_agent="claude",
            transcript_files="[]",
            native_log_file=None,
            last_activity=last_stop,
            last_message_sent_at=last_stop,
            last_agent_stop_at=last_stop,
        )
        service = SimpleNamespace(get_session_data=AsyncMock(return_value={"messages": "terminal tail output"}))

        with (
            patch(
                "teleclaude.api.sessions_actions_routes.check_session_access", new=AsyncMock()
            ) as check_session_access,
            patch.object(sessions_actions_routes, "db") as db,
            patch.object(sessions_actions_routes, "get_command_service", return_value=service),
        ):
            db.get_session = AsyncMock(return_value=session)

            response = await sessions_actions_routes.get_session_messages(
                http_request,
                "sess-tail",
                query=SessionMessagesQuery(
                    since="2025-02-01T00:00:00Z",
                    include_tools=False,
                    include_thinking=False,
                    tail_chars=0,
                ),
                _identity=identity,
            )

        assert response.session_id == "sess-tail"
        assert response.agent == "claude"
        assert response.agent_status == "idle"
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
    async def test_run_session_translates_codex_next_command_to_loader_message(self) -> None:
        """Codex lifecycle workers keep slash metadata but inject the loader message."""
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
        expected_startup = (
            sessions_actions_routes._build_codex_loader_message(
                "next-review-build",
                "chartest-api-routes --direct",
            )
            + "\n\nADDITIONAL CONTEXT:\nTrace real route behavior."
        )
        expected_role = sessions_actions_routes.COMMAND_ROLE_MAP[sessions_actions_routes.SlashCommand.NEXT_REVIEW_BUILD]
        assert command_name == "new_session"
        assert payload == {
            "skip_listener_registration": True,
            "initiator_session_id": "caller-123",
            "initial_input": expected_title,
        }
        assert isinstance(metadata, MessageMetadata)
        assert metadata.origin == InputOrigin.TERMINAL.value
        assert metadata.title is None
        assert metadata.project_path == "/repo/demo"
        assert metadata.subdir == "api"
        assert metadata.origin_metadata is None
        assert metadata.launch_intent is not None
        assert metadata.launch_intent.kind == SessionLaunchKind.AGENT_THEN_MESSAGE
        assert metadata.launch_intent.agent == "codex"
        assert metadata.launch_intent.thinking_mode == "med"
        assert metadata.launch_intent.message == expected_startup
        assert metadata.system_role == expected_role[0]
        assert metadata.job == expected_role[1].value

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_run_session_keeps_non_codex_next_command_as_raw_slash_message(self) -> None:
        """Non-Codex agents still receive the original slash command plus args."""
        request = RunSessionRequest(
            command="/next-review-build",
            args="chartest-api-routes --direct",
            project="/repo/demo",
            agent="claude",
            thinking_mode="slow",
        )
        identity = _identity("caller-123", human_role="member", principal="human:member@example.com")
        mapped_command = object()
        service = SimpleNamespace(
            create_session=AsyncMock(return_value={"session_id": "sess-run", "tmux_session_name": "tmux-run"})
        )

        with (
            patch.object(sessions_actions_routes, "assert_agent_enabled", return_value="claude"),
            patch.object(
                sessions_actions_routes.CommandMapper,
                "map_api_input",
                return_value=mapped_command,
            ) as map_api_input,
            patch.object(sessions_actions_routes, "get_command_service", return_value=service),
        ):
            response = await sessions_actions_routes.run_session(request, identity=identity)

        assert response.status == "success"

        _command_name, _payload, metadata = map_api_input.call_args.args
        expected_message = "/next-review-build chartest-api-routes --direct"
        assert isinstance(metadata, MessageMetadata)
        assert metadata.title is None
        assert metadata.launch_intent is not None
        assert metadata.launch_intent.kind == SessionLaunchKind.AGENT_THEN_MESSAGE
        assert metadata.launch_intent.agent == "claude"
        assert metadata.launch_intent.thinking_mode == "slow"
        assert metadata.launch_intent.message == expected_message

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unsubscribe_session_removes_listener_only(self) -> None:
        """Unsubscribe reports listener removed when only the listener axis had state."""
        identity = _identity("caller-unsub")

        with (
            patch(
                "teleclaude.api.sessions_actions_routes.unregister_listener",
                new=AsyncMock(return_value=True),
            ) as unregister_listener,
            patch(
                "teleclaude.api.sessions_actions_routes.close_link_for_member",
                new=AsyncMock(return_value=None),
            ) as close_link,
        ):
            response = await sessions_actions_routes.unsubscribe_session("sess-unsub", identity=identity)

        assert response == {
            "status": "success",
            "listener_removed": True,
            "link_closed": False,
            "link_id": None,
        }
        unregister_listener.assert_awaited_once_with(
            target_session_id="sess-unsub",
            caller_session_id="caller-unsub",
        )
        close_link.assert_awaited_once_with(
            caller_session_id="caller-unsub",
            target_session_id="sess-unsub",
        )

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unsubscribe_session_closes_link_only(self) -> None:
        """Unsubscribe reports link closed when only the link axis had state."""
        identity = _identity("caller-unsub")

        with (
            patch(
                "teleclaude.api.sessions_actions_routes.unregister_listener",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "teleclaude.api.sessions_actions_routes.close_link_for_member",
                new=AsyncMock(return_value="link-abc"),
            ),
        ):
            response = await sessions_actions_routes.unsubscribe_session("sess-unsub", identity=identity)

        assert response == {
            "status": "success",
            "listener_removed": False,
            "link_closed": True,
            "link_id": "link-abc",
        }

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unsubscribe_session_clears_both_axes(self) -> None:
        """Unsubscribe reports both flags true when both axes had state."""
        identity = _identity("caller-unsub")

        with (
            patch(
                "teleclaude.api.sessions_actions_routes.unregister_listener",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "teleclaude.api.sessions_actions_routes.close_link_for_member",
                new=AsyncMock(return_value="link-xyz"),
            ),
        ):
            response = await sessions_actions_routes.unsubscribe_session("sess-unsub", identity=identity)

        assert response == {
            "status": "success",
            "listener_removed": True,
            "link_closed": True,
            "link_id": "link-xyz",
        }

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unsubscribe_session_idempotent_on_empty_state(self) -> None:
        """Unsubscribe returns success with both flags false when nothing was subscribed."""
        identity = _identity("caller-unsub")

        with (
            patch(
                "teleclaude.api.sessions_actions_routes.unregister_listener",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "teleclaude.api.sessions_actions_routes.close_link_for_member",
                new=AsyncMock(return_value=None),
            ),
        ):
            response = await sessions_actions_routes.unsubscribe_session("sess-unsub", identity=identity)

        assert response == {
            "status": "success",
            "listener_removed": False,
            "link_closed": False,
            "link_id": None,
        }

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_send_result_delegates_to_command_service(self) -> None:
        """Result endpoint constructs SystemCommand and delegates to CommandService."""
        identity = _identity("sess-result")
        request = SendResultRequest(content="**ship it**")
        expected = {"status": "success", "message_id": "msg-1"}

        mock_service = MagicMock()
        mock_service.deliver_result = AsyncMock(return_value=expected)

        with patch("teleclaude.api.sessions_actions_routes.get_command_service", return_value=mock_service):
            response = await sessions_actions_routes.send_result_endpoint(request, identity=identity)

        assert response == expected
        mock_service.deliver_result.assert_awaited_once()
        cmd = mock_service.deliver_result.await_args[0][0]
        assert cmd.command == "deliver_result"
        assert cmd.session_id == "sess-result"
        assert cmd.data["content"] == "**ship it**"

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_render_widget_delegates_to_command_service(self) -> None:
        """Widget endpoint constructs SystemCommand and delegates to CommandService."""
        request = RenderWidgetRequest(
            data={
                "title": "Release status",
                "sections": [{"type": "text", "label": "Summary", "content": "Everything shipped."}],
            }
        )
        identity = _identity("sess-widget")
        expected = {"status": "success", "summary": "**Release status**\n_Summary_\nEverything shipped."}

        mock_service = MagicMock()
        mock_service.render_widget = AsyncMock(return_value=expected)

        with patch("teleclaude.api.sessions_actions_routes.get_command_service", return_value=mock_service):
            response = await sessions_actions_routes.render_widget_endpoint(request, identity=identity)

        assert response == expected
        mock_service.render_widget.assert_awaited_once()
        cmd = mock_service.render_widget.await_args[0][0]
        assert cmd.command == "render_widget"
        assert cmd.session_id == "sess-widget"
        assert cmd.data["widget_data"] == request.data

    @pytest.mark.unit
    def test_run_session_injects_caller_email_into_origin_metadata(self) -> None:
        """Email from CallerIdentity is injected into typed origin metadata for identity resolution."""
        request = RunSessionRequest(
            command="/next-build",
            args="my-slug",
            project="/repo/demo",
        )
        identity = CallerIdentity(
            session_id="caller-123",
            system_role=None,
            human_role=None,
            tmux_session_name=None,
            email="alice@example.com",
        )
        plan = sessions_actions_routes._prepare_run_session(request, identity)
        assert plan.origin_metadata is not None
        assert plan.origin_metadata["email"] == "alice@example.com"

    @pytest.mark.unit
    def test_run_session_assigns_prepare_orchestrator_role_from_command_role_map(self) -> None:
        """The route contract for /next-prepare uses orchestrator role."""
        request = RunSessionRequest(
            command="/next-prepare",
            args="edge-http-migration",
            project="/repo/demo",
        )
        identity = _identity("daemon-session", principal="system:daemon-session")

        plan = sessions_actions_routes._prepare_run_session(request, identity)
        role_info = sessions_actions_routes.COMMAND_ROLE_MAP[sessions_actions_routes.SlashCommand.NEXT_PREPARE]

        assert role_info == (ROLE_ORCHESTRATOR, JobRole.PREPARE_ORCHESTRATOR)
        assert plan.system_role == ROLE_ORCHESTRATOR
        assert plan.job == JobRole.PREPARE_ORCHESTRATOR.value

    @pytest.mark.unit
    def test_run_session_assigns_integrator_role_from_command_role_map(self) -> None:
        """Integrator launches keep the integrator role mapping when routed through POST /sessions/run."""
        request = RunSessionRequest(
            command="/next-integrate",
            args="",
            project="/repo/demo",
        )
        identity = _identity("daemon-session", principal="system:daemon-session")

        plan = sessions_actions_routes._prepare_run_session(request, identity)
        role_info = sessions_actions_routes.COMMAND_ROLE_MAP[sessions_actions_routes.SlashCommand.NEXT_INTEGRATE]

        assert role_info == (ROLE_INTEGRATOR, JobRole.INTEGRATOR)
        assert plan.system_role == ROLE_INTEGRATOR
        assert plan.job == JobRole.INTEGRATOR.value

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_run_session_accepts_terminal_identity_without_session_id(self) -> None:
        """Terminal/TUI callers with human_role but no session_id are accepted.

        Clearance is enforced by the dependency — the endpoint must not
        additionally require a session_id, since CLI and TUI callers
        legitimately lack one.
        """
        request = RunSessionRequest(
            command="/next-integrate",
            args="",
            project="/repo/demo",
        )
        identity = _identity("", human_role="admin")

        service = MagicMock()
        service.create_session = AsyncMock(
            return_value={"session_id": "sess-integrator", "tmux_session_name": "tmux-int"},
        )

        with (
            patch.object(sessions_actions_routes, "get_command_service", return_value=service),
        ):
            response = await sessions_actions_routes.run_session(request, identity=identity)

        assert response.status == "success"
        assert response.session_id == "sess-integrator"
        service.create_session.assert_awaited_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_orchestrator_cannot_dispatch_integrate(self) -> None:
        """Orchestrator system_role is blocked from dispatching /next-integrate."""
        request = RunSessionRequest(command="/next-integrate", args="some-slug", project="/repo/demo")
        identity = _system_identity("sess-orch", system_role=ROLE_ORCHESTRATOR)

        with pytest.raises(HTTPException) as exc_info:
            await sessions_actions_routes.run_session(request, identity=identity)

        assert exc_info.value.status_code == 403
        assert "cannot dispatch" in str(exc_info.value.detail)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_worker_cannot_dispatch_build(self) -> None:
        """Worker system_role cannot dispatch any command."""
        request = RunSessionRequest(command="/next-build", args="some-slug", project="/repo/demo")
        identity = _system_identity("sess-worker", system_role=ROLE_WORKER)

        with pytest.raises(HTTPException) as exc_info:
            await sessions_actions_routes.run_session(request, identity=identity)

        assert exc_info.value.status_code == 403
        assert "cannot dispatch" in str(exc_info.value.detail)

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_orchestrator_can_dispatch_worker_command(self) -> None:
        """Orchestrator system_role can dispatch worker commands like /next-build."""
        request = RunSessionRequest(command="/next-build", args="some-slug", project="/repo/demo")
        identity = _system_identity("sess-orch", system_role=ROLE_ORCHESTRATOR)

        service = MagicMock()
        service.create_session = AsyncMock(
            return_value={"session_id": "sess-builder", "tmux_session_name": "tmux-build"},
        )

        with patch.object(sessions_actions_routes, "get_command_service", return_value=service):
            response = await sessions_actions_routes.run_session(request, identity=identity)

        assert response.status == "success"
        assert response.session_id == "sess-builder"
        service.create_session.assert_awaited_once()

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_escalate_session_returns_503_without_discord_adapter(self) -> None:
        """Escalation returns 503 when CommandService raises ValueError (no Discord adapter)."""
        request = EscalateRequest(customer_name="Taylor", reason="handoff")
        identity = _identity("sess-escalate", human_role="customer")

        mock_service = MagicMock()
        mock_service.escalate_session = AsyncMock(
            side_effect=ValueError("Discord adapter not available"),
        )

        with patch("teleclaude.api.sessions_actions_routes.get_command_service", return_value=mock_service):
            with pytest.raises(HTTPException) as exc_info:
                await sessions_actions_routes.escalate_session(request, identity=identity)

        assert exc_info.value.status_code == 503
        mock_service.escalate_session.assert_awaited_once()
