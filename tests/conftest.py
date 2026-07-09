"""Pytest configuration and shared fixtures for the TeleClaude suite."""
# pylint: disable=broad-exception-caught,import-outside-toplevel

import atexit
import dataclasses
import importlib
import logging
import os
import shutil
import tempfile
from collections.abc import AsyncGenerator, Awaitable, Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

# RuntimeConfig must be seeded before any other teleclaude module is imported,
# because paths.py derives its module-level constants from get_runtime_config().
_repo_root = Path(__file__).resolve().parents[1]
_inherited_tmpdir = os.environ.get("TMPDIR") or os.environ.get("TMP") or os.environ.get("TEMP")
_test_worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
_test_worker_tmpdir = Path(tempfile.mkdtemp(prefix=f"teleclaude-pytest-tmpdir-{_test_worker_id}-")).resolve()
if _inherited_tmpdir:
    _session_identity_file = Path(_inherited_tmpdir) / "teleclaude_identity.json"
    if _session_identity_file.exists():
        shutil.copy2(_session_identity_file, _test_worker_tmpdir / _session_identity_file.name)
for _temp_env_var in ("TMPDIR", "TMP", "TEMP"):
    os.environ[_temp_env_var] = str(_test_worker_tmpdir)
atexit.register(shutil.rmtree, _test_worker_tmpdir, ignore_errors=True)

_test_runtime_root = Path(tempfile.mkdtemp(prefix="teleclaude-pytest-")).resolve()
atexit.register(shutil.rmtree, _test_runtime_root, ignore_errors=True)

from teleclaude.runtime.config import RuntimeConfig, set_runtime_config

set_runtime_config(
    RuntimeConfig(
        home=_test_runtime_root / ".teleclaude",
        config_path=_repo_root / "tests" / "integration" / "config.yml",
        env_path=_repo_root / "tests" / "integration" / ".env",
    )
)

import teleclaude.paths as tc_paths
from teleclaude import config as config_module
from teleclaude import paths
from teleclaude.api import auth as auth_mod
from teleclaude.api_server import APIServer
from teleclaude.core import tmux_bridge
from teleclaude.core.command_handlers import _session as session_handler_mod
from teleclaude.core.command_registry import init_command_service, reset_command_service
from teleclaude.core.command_service import CommandService
from teleclaude.core.db import Db
from teleclaude.core.event_bus import event_bus
from teleclaude.core.identity import IdentityContext
from teleclaude.core.tmux_bridge import _session as tmux_session_mod


class _ClusterEmitRedisFake:
    async def xadd(self, _stream: str, _data: dict[str, str], **_kwargs: object) -> str:
        return "test-event-1-0"


try:
    import instrukt_ai_logging  # startup boundary

    def _noop_configure_logging(*_args, **_kwargs):
        return None

    instrukt_ai_logging.configure_logging = _noop_configure_logging
    logging.getLogger("teleclaude").handlers.clear()
    logging.getLogger().handlers.clear()
except Exception:
    pass


@pytest.fixture(autouse=True)
def _reset_event_bus():
    """Ensure global event bus handlers do not leak across tests."""
    event_bus.clear()
    reset_command_service()
    yield
    event_bus.clear()
    reset_command_service()


@pytest.fixture(scope="session")
def _pristine_config_baseline():
    """Capture the original config singleton object and a deep pristine snapshot.

    Requested during the first test's setup (after session-scoped neutralization),
    so it holds the original ``config`` object — the one every early importer
    (TUI views, etc.) bound via ``from teleclaude.config import config`` — plus a
    deep copy of its section values, including the neutered launcher binaries.
    """
    import copy

    import teleclaude.config as tc_config_module  # startup boundary

    original = tc_config_module.config
    return original, copy.deepcopy(dict(original.__dict__))


@pytest.fixture(autouse=True)
def _restore_config_singleton(_pristine_config_baseline):
    """Restore the global config singleton to its pristine state after each test.

    Config-write paths pollute the singleton three ways: ``reload_config()``
    mutates ``teleclaude.config.config`` in place, some tests mutate section
    objects directly, and the config validator (``config_handlers``) calls
    ``importlib.reload(teleclaude.config)``, which rebinds the module's ``config``
    to a brand-new object. That last one is why a per-test ``__dict__`` snapshot is
    insufficient: after a reload the module global and the object early importers
    (TUI views, tests that did module-level ``from teleclaude.config import
    config``) still hold have diverged, so restoring one leaves the other stuck at
    a fixture value like ``NewMac`` — which breaks local-first ordering in TUI
    tests that read the live config. Rebinding the module to the original object
    and deep-restoring its ``__dict__`` reconverges every holder on one known-clean
    object, cascade-proof regardless of what any prior test did.
    """
    import copy

    import teleclaude.config as tc_config_module  # startup boundary

    original, pristine = _pristine_config_baseline
    yield
    tc_config_module.config = original
    original.__dict__.clear()
    original.__dict__.update(copy.deepcopy(pristine))


@pytest.fixture
def cluster_event_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure EventBus Redis only for tests that exercise CLUSTER emit paths."""
    monkeypatch.setattr(event_bus, "_role", "pytest")
    monkeypatch.setattr(event_bus, "_redis", _ClusterEmitRedisFake())


@pytest.fixture(autouse=True)
def _isolate_tui_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolate TUI sticky state from the user's ~/.teleclaude/tui_state.json."""
    from teleclaude.cli.tui import state_store  # startup boundary

    tui_state = tmp_path / "tui_state.json"
    monkeypatch.setattr(paths, "TUI_STATE_PATH", tui_state)
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", tui_state)
    yield


@pytest.fixture(autouse=True)
def _isolate_test_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Provide a consistent, isolated environment for each test."""
    from teleclaude.core import db as db_module  # startup boundary
    from teleclaude.core import session_cleanup, session_utils  # startup boundary
    from teleclaude.runtime import config as _rc_module  # startup boundary
    from teleclaude.runtime.config import get_runtime_config  # startup boundary

    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    config_path = project_root / "teleclaude.yml"
    if not config_path.exists():
        config_path.write_text("business:\n  domains:\n    software-development: docs\n", encoding="utf-8")

    # Patch the RuntimeConfig singleton for this test; monkeypatch restores it afterwards.
    monkeypatch.setattr(
        _rc_module,
        "_instance",
        dataclasses.replace(get_runtime_config(), project_config_path=config_path),
    )
    db_module.db.db_path = str(tc_paths.MAIN_DB_PATH)

    try:
        workspace_root = tmp_path / "workspace"
        monkeypatch.setattr(session_utils, "OUTPUT_DIR", workspace_root, raising=False)
        monkeypatch.setattr(session_cleanup, "OUTPUT_DIR", workspace_root, raising=False)
    except Exception:
        pass

    yield


@pytest.fixture(scope="session", autouse=True)
def _redirect_home(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Redirect $HOME so un-mocked ``Path.home()`` writes can't touch the host.

    The runtime home is already sandboxed via ``RuntimeConfig.home`` (see the
    conftest module preamble), but install-time writers such as
    ``configure_agent_cli`` address ``Path.home()/.claude`` etc. directly. With
    no test exercising them today this is latent, but redirecting $HOME makes the
    isolation structural rather than by-convention.
    """
    home = tmp_path_factory.mktemp("home")
    mp = pytest.MonkeyPatch()
    mp.setenv("HOME", str(home))
    mp.setenv("USERPROFILE", str(home))
    try:
        yield
    finally:
        mp.undo()


@pytest.fixture(scope="session", autouse=True)
def _neutralize_launcher_binaries():
    """Keep any un-mocked subprocess call from executing real launcher binaries."""
    from teleclaude.config import config as tc_config  # startup boundary
    from teleclaude.runtime import binaries as binaries_mod  # startup boundary

    mp = pytest.MonkeyPatch()
    mp.setattr(tc_config.computer, "tmux_binary", "/dev/null/tmux-NEUTERED")
    for agent_cfg in tc_config.agents.values():
        mp.setattr(agent_cfg, "binary", f"/dev/null/{agent_cfg.binary}-NEUTERED")
    mp.setattr(binaries_mod, "_is_macos", lambda: False)
    try:
        yield mp
    finally:
        mp.undo()


@pytest.fixture
async def api(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncGenerator[AsyncClient, None]:
    """Spin up the real FastAPI app backed by in-memory SQLite.

    Mocks only tmux (no real processes) and adapters (no network).
    Returns an httpx AsyncClient that speaks ASGI directly to the app.
    """
    # --- DB: in-memory SQLite ---
    test_db = Db(":memory:")
    await test_db.initialize()

    # Patch the canonical db singleton. All modules import `db` from
    # `teleclaude.core.db`, which re-exports it from `_base`. Patch both
    # the package attribute and every module that has already cached it.
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
    class _StubIdentityResolver:
        registered_people_count = 1
        is_multi_user = False

        @staticmethod
        def resolve_by_email(email: str) -> IdentityContext:
            """Return a stable single-user admin identity for the harness."""
            normalized = email.strip().lower()
            if normalized == "test@test.com":
                return IdentityContext(person_name="test", person_email=normalized, person_role="admin")
            return IdentityContext()

    def _get_identity_resolver() -> _StubIdentityResolver:
        """Return the functional-test identity resolver."""
        return _StubIdentityResolver()

    monkeypatch.setattr(auth_mod, "get_identity_resolver", _get_identity_resolver)

    # --- tmux: no-op ---
    _created = set()

    async def _mock_create(name, working_dir, cols=80, rows=24, session_id=None, env_vars=None):
        """Pretend tmux session creation succeeded without shelling out."""
        _created.add(name)
        return True

    # Mock at the submodule level (where handlers import from) AND package level.
    monkeypatch.setattr(tmux_session_mod, "ensure_tmux_session", _mock_create)
    monkeypatch.setattr(tmux_bridge, "ensure_tmux_session", _mock_create)
    monkeypatch.setattr(tmux_bridge, "session_exists", AsyncMock(return_value=True))
    monkeypatch.setattr(tmux_bridge, "kill_session", AsyncMock(return_value=True))
    monkeypatch.setattr(tmux_bridge, "get_pane_process_tree", AsyncMock(return_value=[]))
    monkeypatch.setattr(tmux_bridge, "wait_for_processes_exit", AsyncMock(return_value=[]))
    monkeypatch.setattr(tmux_bridge, "send_keys", AsyncMock(return_value=True))
    monkeypatch.setattr(tmux_bridge, "send_keys_existing_tmux", AsyncMock(return_value=True))
    monkeypatch.setattr(tmux_bridge, "capture_pane", AsyncMock(return_value=""))
    monkeypatch.setattr(tmux_bridge, "is_process_running", AsyncMock(return_value=False))
    monkeypatch.setattr(tmux_bridge, "start_pipe_pane", AsyncMock(return_value=True))
    monkeypatch.setattr(tmux_bridge, "get_pane_tty", AsyncMock(return_value=None))
    monkeypatch.setattr(tmux_bridge, "get_pane_pid", AsyncMock(return_value=None))

    # --- Config: mock computer ---
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
    monkeypatch.setattr(session_handler_mod, "config", config_module.config)

    # --- Identity resolver: no platform identity ---

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
    reset_command_service()

    async def _noop_bootstrap(session_id, launch_intent=None):
        """Stand in for the daemon bootstrap task during functional tests."""
        del session_id, launch_intent
        return None

    def _discard_background_task(task: Awaitable[object], _name: str | None = None) -> None:
        """Close discarded coroutine objects so pytest does not flag them as unawaited."""
        close = getattr(task, "close", None)
        if callable(close):
            close()

    cmd_service = CommandService(
        client=stub_client,
        start_polling=AsyncMock(),
        execute_terminal_command=AsyncMock(),
        queue_background_task=_discard_background_task,
        bootstrap_session=_noop_bootstrap,
    )
    init_command_service(cmd_service, force=True)

    # --- Build real FastAPI app ---
    server = APIServer(client=stub_client, cache=None)

    # --- httpx async client over ASGI ---
    transport = ASGITransport(app=server.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.db = test_db  # expose for direct inspection in tests
        yield client

    await test_db.close()
