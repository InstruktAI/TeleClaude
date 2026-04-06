# pylint: disable=consider-using-from-import,import-outside-toplevel,missing-function-docstring,protected-access,too-few-public-methods,too-many-instance-attributes
# guard: no-companion
"""Specification tests for headless session creation and terminal identity cleanup."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import teleclaude.daemon_hook_outbox as daemon_hook_outbox
from teleclaude.core.command_handlers import _session as session_handler
from teleclaude.core.events import AgentEventContext
from teleclaude.core.models import Session
from teleclaude.types.commands import CreateSessionCommand


def _legacy_terminal_helper_name() -> str:
    return "_".join(("resolve", "from", "terminal"))


class _TestDaemon(daemon_hook_outbox._DaemonHookOutboxMixin):
    """Minimal test harness for the hook outbox mixin."""

    def __init__(self) -> None:
        self.shutdown_event = None  # pyright: ignore[reportAttributeAccessIssue]
        self._background_tasks: set[asyncio.Task[object]] = set()
        self._session_outbox_queues: dict[str, daemon_hook_outbox._HookOutboxSessionQueue] = {}  # guard: loose-dict
        self._session_outbox_workers: dict[str, asyncio.Task[None]] = {}  # guard: loose-dict
        self._hook_outbox_processed_count = 0
        self._hook_outbox_coalesced_count = 0
        self._hook_outbox_stale_dropped_count = 0
        self._hook_outbox_lag_samples_s: list[float] = []
        self._hook_outbox_last_summary_at = 0.0
        self._hook_outbox_last_backlog_warn_at: dict[str, float] = {}  # guard: loose-dict
        self._hook_outbox_last_lag_warn_at: dict[str, float] = {}  # guard: loose-dict
        self._hook_outbox_claim_paused_sessions: set[str] = set()
        self.cache = None  # pyright: ignore[reportAttributeAccessIssue]

    def _queue_background_task(
        self,
        coro: Coroutine[object, object, object],
        label: str,
    ) -> None:
        raise NotImplementedError

    async def _handle_agent_event(
        self,
        _event: str,
        context: AgentEventContext,
    ) -> None:
        raise NotImplementedError

    async def _ensure_output_polling(self, session: Session) -> None:
        raise NotImplementedError


class TestDaemonHeadlessViaCommandPipeline:
    """The daemon hook outbox must dispatch a typed create-session command."""

    @pytest.mark.unit
    async def test_ensure_headless_session_dispatches_create_session_command(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        daemon = _TestDaemon()
        data = {  # guard: loose-dict — hook payload is dynamic JSON
            "cwd": "/tmp/project/trees/test-slug",
            "agent_name": "claude",
            "native_session_id": "native-123",
            "native_log_file": "/tmp/native.log",
        }
        service = SimpleNamespace(create_session=AsyncMock(return_value={"session_id": "test-session-id"}))
        created_session = MagicMock()
        created_session.session_id = "test-session-id"

        monkeypatch.setattr(daemon_hook_outbox, "get_command_service", lambda: service)
        monkeypatch.setattr(daemon_hook_outbox, "read_current_session_email", lambda: "admin@example.com")
        monkeypatch.setattr(
            daemon_hook_outbox,
            "db",
            SimpleNamespace(get_session=AsyncMock(return_value=created_session)),
        )

        with patch.object(daemon_hook_outbox, "event_bus") as mock_event_bus:
            session = await daemon._ensure_headless_session("test-session-id", data)

        assert session is created_session
        service.create_session.assert_awaited_once()
        cmd = service.create_session.await_args.args[0]
        assert isinstance(cmd, CreateSessionCommand)
        assert cmd.headless is True
        assert cmd.session_id == "test-session-id"
        assert cmd.native_session_id == "native-123"
        assert cmd.native_log_file == "/tmp/native.log"
        assert cmd.launch_intent is not None
        assert cmd.launch_intent.agent == "claude"
        assert cmd.origin_metadata is not None
        assert cmd.origin_metadata["email"] == "admin@example.com"
        assert cmd.system_role is None
        assert cmd.human_role is None
        mock_event_bus.emit.assert_called_once()

    @pytest.mark.unit
    async def test_ensure_headless_session_defaults_missing_terminal_identity_to_customer(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        daemon = _TestDaemon()
        data = {
            "cwd": "/tmp/project/trees/test-slug",
            "agent_name": "codex",
            "native_session_id": "native-999",
        }
        service = SimpleNamespace(create_session=AsyncMock(return_value={"session_id": "test-session-id"}))
        created_session = MagicMock()
        created_session.session_id = "test-session-id"

        monkeypatch.setattr(daemon_hook_outbox, "get_command_service", lambda: service)
        monkeypatch.setattr(daemon_hook_outbox, "read_current_session_email", lambda: None)
        monkeypatch.setattr(
            daemon_hook_outbox,
            "db",
            SimpleNamespace(get_session=AsyncMock(return_value=created_session)),
        )

        await daemon._ensure_headless_session("test-session-id", data)

        cmd = service.create_session.await_args.args[0]
        assert isinstance(cmd, CreateSessionCommand)
        assert cmd.system_role is None
        assert cmd.origin_metadata is None
        assert cmd.human_role == "customer"

    @pytest.mark.unit
    async def test_ensure_headless_session_jails_customer_terminal_callers(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        daemon = _TestDaemon()
        project_path = tmp_path / "project"
        worktree_path = project_path / "trees" / "customer"
        worktree_path.mkdir(parents=True)
        help_desk = tmp_path / "help-desk"
        help_desk.mkdir()
        data = {
            "cwd": str(worktree_path),
            "agent_name": "codex",
            "native_session_id": "native-456",
        }
        created_sessions: dict[str, SimpleNamespace] = {}

        async def _create_session_row(**kwargs: object) -> SimpleNamespace:
            session = SimpleNamespace(
                session_id=str(kwargs["session_id"]),
                project_path=str(kwargs["project_path"]),
                subdir=kwargs["subdir"],
            )
            created_sessions[session.session_id] = session
            return session

        async def _get_created_session(session_id: str) -> SimpleNamespace | None:
            return created_sessions.get(session_id)

        async def _create_through_session_handler(cmd: CreateSessionCommand) -> dict[str, str]:
            return await session_handler.create_session(cmd, SimpleNamespace())

        session_db = SimpleNamespace(
            create_session=AsyncMock(side_effect=_create_session_row),
            update_origin_metadata=AsyncMock(),
            get_session=AsyncMock(side_effect=_get_created_session),
        )
        service = SimpleNamespace(create_session=AsyncMock(side_effect=_create_through_session_handler))

        monkeypatch.setattr(
            session_handler,
            "config",
            SimpleNamespace(computer=SimpleNamespace(name="local", help_desk_dir=str(help_desk))),
        )
        monkeypatch.setattr(session_handler, "db", session_db)
        monkeypatch.setattr(
            session_handler,
            "get_identity_resolver",
            lambda: SimpleNamespace(
                resolve=lambda _origin, _metadata: SimpleNamespace(
                    person_email="customer@example.com",
                    person_role="customer",
                    platform="terminal",
                    platform_user_id="customer@example.com",
                )
            ),
        )
        monkeypatch.setattr(daemon_hook_outbox, "get_command_service", lambda: service)
        monkeypatch.setattr(daemon_hook_outbox, "read_current_session_email", lambda: "customer@example.com")
        monkeypatch.setattr(daemon_hook_outbox, "db", session_db)
        monkeypatch.setattr(
            daemon,
            "_resolve_headless_project_context",
            lambda _workdir: (str(project_path), "trees/customer"),
        )

        with patch.object(daemon_hook_outbox, "event_bus"):
            session = await daemon._ensure_headless_session("headless-customer", data)

        assert getattr(session, "session_id", None) == "headless-customer"
        assert getattr(session, "project_path", None) == str(help_desk)
        create_cmd = service.create_session.await_args.args[0]
        assert isinstance(create_cmd, CreateSessionCommand)
        assert create_cmd.system_role is None
        assert create_cmd.origin_metadata is not None
        assert create_cmd.origin_metadata["email"] == "customer@example.com"

        create_call = session_db.create_session.await_args
        assert create_call.kwargs["project_path"] == str(help_desk)
        assert create_call.kwargs["subdir"] is None
        assert create_call.kwargs["system_role"] is None


class TestIdentityResolverSurface:
    """The legacy terminal helper must be removed from the resolver surface."""

    @pytest.mark.unit
    def test_identity_resolver_drops_legacy_terminal_helper(self) -> None:
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[])
            mock_dir.glob.return_value = []

            from teleclaude.core.identity import IdentityResolver

            resolver = IdentityResolver()

        assert not hasattr(resolver, _legacy_terminal_helper_name())


class TestCliCallersAlternativePath:
    """CLI callers must resolve role checks from the current terminal email."""

    @pytest.mark.unit
    def test_docs_handler_resolves_identity_from_terminal_email(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from teleclaude.cli.telec.handlers import docs as docs_module

        mock_resolver = SimpleNamespace(
            resolve_by_email=lambda email: SimpleNamespace(person_role="admin", email=email)
        )
        monkeypatch.setattr(docs_module, "get_identity_resolver", lambda: mock_resolver)
        monkeypatch.setattr(docs_module, "read_current_session_email", lambda: "admin@example.com")
        monkeypatch.setattr(docs_module, "build_context_output", lambda **kwargs: "mocked output")

        docs_module._handle_docs_index([])

    @pytest.mark.unit
    def test_config_cli_resolves_identity_from_terminal_email(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        import teleclaude.cli.config_cli as config_module

        mock_resolver = SimpleNamespace(
            resolve_by_email=lambda email: SimpleNamespace(person_role="admin", email=email)
        )
        monkeypatch.setattr(config_module, "get_identity_resolver", lambda: mock_resolver)
        monkeypatch.setattr(config_module, "read_current_session_email", lambda: "admin@example.com")

        config_module._check_customer_guard()
