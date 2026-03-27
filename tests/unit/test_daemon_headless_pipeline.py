# guard: no-companion
"""Test spec (xfail) for R6: daemon headless session creation via command pipeline.

The daemon's headless session creation must go through CreateSessionCommand pipeline
instead of calling db.create_headless_session() directly. resolve_from_terminal()
must be removed. CLI callers must use an alternative path.

Remove ``pytestmark = pytest.mark.xfail`` once all tests pass after implementation.
"""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import teleclaude.daemon_hook_outbox as daemon_hook_outbox
from teleclaude.core.events import AgentEventContext
from teleclaude.core.models import Session

pytestmark = pytest.mark.xfail


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
    """R6: Daemon hook outbox constructs CreateSessionCommand instead of direct DB call."""

    @pytest.mark.unit
    async def test_ensure_headless_session_does_not_call_db_directly(self) -> None:
        """_ensure_headless_session must not call db.create_headless_session() directly."""
        daemon = _TestDaemon()
        data = {  # guard: loose-dict — hook payload is dynamic JSON
            "cwd": "/tmp/project/trees/test-slug",
            "agent_name": "claude",
            "native_session_id": "native-123",
        }

        with patch.object(daemon_hook_outbox, "db", new_callable=MagicMock) as mock_db:
            mock_db.create_headless_session = AsyncMock()
            mock_db.get_session = AsyncMock(return_value=None)
            try:
                await daemon._ensure_headless_session("test-session-id", data)
            except NotImplementedError:
                pass  # _queue_background_task raises NotImplementedError in test harness

            assert not mock_db.create_headless_session.called, (
                "db.create_headless_session must not be called directly; use CreateSessionCommand pipeline instead"
            )

    @pytest.mark.unit
    async def test_headless_session_does_not_call_resolve_from_terminal(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Identity must propagate via initiator_session_id, not resolve_from_terminal()."""
        resolve_called = False

        def track_resolve_from_terminal() -> SimpleNamespace:
            nonlocal resolve_called
            resolve_called = True
            return SimpleNamespace(person_email=None, person_role=None)

        def _resolve(_origin: str, _metadata: object) -> SimpleNamespace:
            return SimpleNamespace(
                person_email="admin@example.com",
                person_role="admin",
                platform="terminal",
                platform_user_id="admin@example.com",
            )

        mock_resolver = SimpleNamespace(
            resolve_from_terminal=track_resolve_from_terminal,
            resolve=_resolve,
        )
        monkeypatch.setattr(
            daemon_hook_outbox,
            "get_identity_resolver",
            lambda: mock_resolver,
        )

        daemon = _TestDaemon()
        data = {  # guard: loose-dict — hook payload is dynamic JSON
            "cwd": "/tmp/project",
            "agent_name": "claude",
        }

        try:
            await daemon._ensure_headless_session("test-session-id", data)
        except NotImplementedError:
            pass  # _queue_background_task raises NotImplementedError in test harness

        assert not resolve_called, (
            "resolve_from_terminal() must not be called; identity propagates via initiator_session_id"
        )


class TestResolveFromTerminalRemoved:
    """R6: resolve_from_terminal() must be removed from the identity resolver."""

    @pytest.mark.unit
    def test_identity_resolver_has_no_resolve_from_terminal(self) -> None:
        """IdentityResolver must not have a resolve_from_terminal method."""
        with (
            patch("teleclaude.core.identity.load_global_config") as mock_cfg,
            patch("teleclaude.core.identity._PEOPLE_DIR") as mock_dir,
        ):
            mock_cfg.return_value = MagicMock(people=[])
            mock_dir.glob.return_value = []

            from teleclaude.core.identity import IdentityResolver

            resolver = IdentityResolver()

        assert not hasattr(resolver, "resolve_from_terminal"), (
            "resolve_from_terminal must be removed from IdentityResolver"
        )


class TestCliCallersAlternativePath:
    """R6: CLI callers of resolve_from_terminal use alternative path.

    Each test provides a mock resolver that has resolve/resolve_by_email but NOT
    resolve_from_terminal. If the caller still calls resolve_from_terminal, it raises
    AttributeError (caught by xfail). After R6 wires the alternative path, the caller
    works with the mock and the test passes.
    """

    @pytest.mark.unit
    def test_docs_handler_resolves_identity_without_resolve_from_terminal(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Docs handler must resolve identity without resolve_from_terminal."""
        from teleclaude.cli.telec.handlers import docs as docs_module

        def _resolve(origin: str, metadata: object) -> SimpleNamespace:
            return SimpleNamespace(
                person_role="admin",
                person_email="admin@example.com",
                person_name="Admin",
                platform="terminal",
                platform_user_id="admin@example.com",
            )

        def _resolve_by_email(email: str) -> SimpleNamespace:
            return SimpleNamespace(person_role="admin", person_email=email)

        mock_resolver = SimpleNamespace(resolve=_resolve, resolve_by_email=_resolve_by_email)
        monkeypatch.setattr(docs_module, "get_identity_resolver", lambda: mock_resolver)

        def _mock_build_context(**kwargs: object) -> str:
            return "mocked output"

        monkeypatch.setattr(docs_module, "build_context_output", _mock_build_context)

        # _handle_docs_index resolves identity internally.
        # If it calls resolve_from_terminal, AttributeError will be raised (mock lacks it).
        docs_module._handle_docs_index([])

    @pytest.mark.unit
    def test_config_cli_resolves_identity_without_resolve_from_terminal(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Config CLI customer guard must resolve identity without resolve_from_terminal."""
        import teleclaude.cli.config_cli as config_module

        def _resolve(origin: str, metadata: object) -> SimpleNamespace:
            return SimpleNamespace(person_role="admin")

        def _resolve_by_email(email: str) -> SimpleNamespace:
            return SimpleNamespace(person_role="admin")

        mock_resolver = SimpleNamespace(resolve=_resolve, resolve_by_email=_resolve_by_email)
        monkeypatch.setattr(config_module, "get_identity_resolver", lambda: mock_resolver)

        # _check_customer_guard calls get_identity_resolver().resolve_from_terminal().
        # If it still uses resolve_from_terminal, AttributeError raised (mock lacks it).
        config_module._check_customer_guard()

    @pytest.mark.unit
    def test_cartridge_cli_resolves_identity_without_resolve_from_terminal(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Cartridge CLI admin check must resolve identity without resolve_from_terminal."""

        def _resolve(origin: str, metadata: object) -> SimpleNamespace:
            return SimpleNamespace(person_role="admin")

        def _resolve_by_email(email: str) -> SimpleNamespace:
            return SimpleNamespace(person_role="admin")

        mock_resolver = SimpleNamespace(resolve=_resolve, resolve_by_email=_resolve_by_email)
        # cartridge_cli uses a local import — patch the source module
        monkeypatch.setattr(
            "teleclaude.core.identity.get_identity_resolver",
            lambda: mock_resolver,
        )

        import teleclaude.cli.cartridge_cli as cartridge_module

        # _caller_is_admin calls get_identity_resolver().resolve_from_terminal().
        # If it still uses resolve_from_terminal, AttributeError raised (mock lacks it).
        result = cartridge_module._caller_is_admin()
        assert isinstance(result, bool), "Identity resolution must return a usable result"
