"""Pytest configuration and shared fixtures for the TeleClaude suite."""
# pylint: disable=broad-exception-caught,import-outside-toplevel

import atexit
import dataclasses
import logging
import shutil
import tempfile
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


@pytest.fixture(autouse=True)
def _restore_config_singleton():
    """Restore the global config singleton after each test.

    ``reload_config()`` mutates ``teleclaude.config.config`` in place, and tests
    that exercise reload paths leave the singleton pointed at a fixture config.
    Snapshot the singleton's attributes before the test and restore them after so
    that pollution (e.g. an all-off ``workflow`` section) never leaks to later
    tests that read the live config.
    """
    from teleclaude.config import config as tc_config  # startup boundary

    snapshot = dict(tc_config.__dict__)
    yield
    tc_config.__dict__.clear()
    tc_config.__dict__.update(snapshot)


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
