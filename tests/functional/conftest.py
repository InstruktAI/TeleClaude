"""Functional test fixtures — real FastAPI app, real auth, real DB, no network."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

# Point config at the minimal test config before any teleclaude imports.
os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

pytestmark = pytest.mark.functional


@pytest.fixture
async def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncGenerator[AsyncClient, None]:
    """Spin up the real FastAPI app backed by in-memory SQLite.

    Mocks only tmux (no real processes) and adapters (no network).
    Returns an httpx AsyncClient that speaks ASGI directly to the app.
    """
    # --- DB: in-memory SQLite ---
    from teleclaude.core.db import Db

    test_db = Db(":memory:")
    await test_db.initialize()

    # Patch the canonical db singleton. All modules import `db` from
    # `teleclaude.core.db`, which re-exports it from `_base`. Patch both
    # the package attribute and every module that has already cached it.
    import importlib

    db_mod = importlib.import_module("teleclaude.core.db")
    monkeypatch.setattr(db_mod, "db", test_db)

    # Force-import modules that use `from teleclaude.core.db import db` so
    # their module-level `db` binding is replaced too.
    for mod_name in [
        "teleclaude.core.command_handlers._session",
        "teleclaude.core.command_handlers._agent",
        "teleclaude.core.command_handlers._keys",
        "teleclaude.core.command_handlers",
        "teleclaude.core.session_cleanup",
        "teleclaude.api.auth",
        "teleclaude.api.sessions_routes",
        "teleclaude.api.sessions_actions_routes",
        "teleclaude.api_server",
    ]:
        mod = importlib.import_module(mod_name)
        if hasattr(mod, "db"):
            monkeypatch.setattr(mod, "db", test_db)

    # --- Config: single-user mode (no login required → admin) ---
    from teleclaude.api.auth import _EMAIL_ROLE_CACHE_STATE

    _EMAIL_ROLE_CACHE_STATE.role_map = {}
    _EMAIL_ROLE_CACHE_STATE.mtime_ns = 0
    _EMAIL_ROLE_CACHE_STATE.registered_people_count = 1  # single user

    # --- tmux: no-op ---
    from teleclaude.core import tmux_bridge

    _created = set()

    async def _mock_create(name, working_dir, cols=80, rows=24, session_id=None, env_vars=None):
        _created.add(name)
        return True

    # Mock at the submodule level (where handlers import from) AND package level.
    from teleclaude.core.tmux_bridge import _session as tmux_session_mod

    monkeypatch.setattr(tmux_session_mod, "ensure_tmux_session", _mock_create)
    monkeypatch.setattr(tmux_bridge, "ensure_tmux_session", _mock_create)
    monkeypatch.setattr(tmux_bridge, "session_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(tmux_bridge, "kill_session", AsyncMock(return_value=True))
    monkeypatch.setattr(tmux_bridge, "send_keys", AsyncMock(return_value=True))
    monkeypatch.setattr(tmux_bridge, "send_keys_existing_tmux", AsyncMock(return_value=True))
    monkeypatch.setattr(tmux_bridge, "capture_pane", AsyncMock(return_value=""))
    monkeypatch.setattr(tmux_bridge, "is_process_running", AsyncMock(return_value=False))
    monkeypatch.setattr(tmux_bridge, "start_pipe_pane", AsyncMock(return_value=True))
    monkeypatch.setattr(tmux_bridge, "get_pane_tty", AsyncMock(return_value=None))
    monkeypatch.setattr(tmux_bridge, "get_pane_pid", AsyncMock(return_value=None))

    # --- Config: mock computer ---
    from teleclaude import config as config_module

    mock_computer = SimpleNamespace(
        name="TestComputer",
        default_working_dir=str(tmp_path),
        default_shell="/bin/sh",
        tmux_binary="tmux",
        user="testuser",
        role="test",
        host="test.local",
        timezone="UTC",
        is_master=False,
        trusted_dirs=[],
        help_desk_dir=str(tmp_path / "help-desk"),
        get_all_trusted_dirs=lambda: [],
    )
    monkeypatch.setattr(config_module.config, "computer", mock_computer)

    # Patch config in session handler module too.
    from teleclaude.core.command_handlers import _session as session_handler_mod

    monkeypatch.setattr(session_handler_mod, "config", config_module.config)

    # --- Identity resolver: no platform identity ---
    from teleclaude.core.identity import IdentityContext

    _no_identity = IdentityContext()
    _mock_resolver = SimpleNamespace(resolve=lambda _origin, _meta: _no_identity)
    monkeypatch.setattr(session_handler_mod, "get_identity_resolver", lambda: _mock_resolver)

    # --- Adapter client: empty shell ---
    stub_client = SimpleNamespace(
        adapters={},
        send_message=AsyncMock(return_value="msg-1"),
        start=AsyncMock(),
        stop=AsyncMock(),
    )

    # --- CommandService: wired with no-op callbacks ---
    from teleclaude.core.command_registry import init_command_service, reset_command_service
    from teleclaude.core.command_service import CommandService

    reset_command_service()

    async def _noop_bootstrap(session_id, auto_command=None):
        pass

    cmd_service = CommandService(
        client=stub_client,
        start_polling=AsyncMock(),
        execute_terminal_command=AsyncMock(),
        execute_auto_command=AsyncMock(),
        queue_background_task=lambda coro, name=None: None,
        bootstrap_session=_noop_bootstrap,
    )
    init_command_service(cmd_service, force=True)

    # --- Build real FastAPI app ---
    from teleclaude.api_server import APIServer

    server = APIServer(client=stub_client, cache=None)

    # --- httpx async client over ASGI ---
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.db = test_db  # expose for direct inspection in tests
        yield client

    await test_db.close()
