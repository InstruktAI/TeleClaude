"""Pytest configuration and shared fixtures for the TeleClaude suite."""
# pylint: disable=broad-exception-caught,import-outside-toplevel

import atexit
import dataclasses
import logging
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# RuntimeConfig must be seeded before any other teleclaude module is imported,
# because paths.py derives its module-level constants from get_runtime_config().
_repo_root = Path(__file__).resolve().parents[1]
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
from teleclaude import paths
from teleclaude.core.command_registry import reset_command_service
from teleclaude.core.event_bus import event_bus


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
