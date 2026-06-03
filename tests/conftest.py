"""Pytest configuration for TeleClaude tests."""
# pylint: disable=wrong-import-position,broad-exception-caught,unused-argument
# pylint: disable=import-outside-toplevel,too-many-positional-arguments
# Pytest fixture modules intentionally use dynamic imports and callback signatures.

import asyncio
import atexit
import logging
import multiprocessing
import os
import shutil
import sys
import tempfile
import time
import warnings
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from teleclaude.quality import test_watchdog as _watchdog

_repo_root = Path(__file__).resolve().parents[1]
_test_runtime_root = Path(tempfile.mkdtemp(prefix="teleclaude-pytest-")).resolve()
atexit.register(shutil.rmtree, _test_runtime_root, ignore_errors=True)

os.environ["TELECLAUDE_HOME"] = str(_test_runtime_root / ".teleclaude")
os.environ.setdefault("TELECLAUDE_CONFIG_PATH", str(_repo_root / "tests" / "integration" / "config.yml"))
os.environ.setdefault("TELECLAUDE_ENV_PATH", str(_repo_root / "tests" / "integration" / ".env"))

# Heavy modules (teleclaude.core.db → SQLAlchemy+greenlet+aiosqlite, teleclaude.config →
# greenlet, teleclaude.cli.tui.state_store → curses, teleclaude.runtime.binaries, the
# session_* core modules) are NOT imported at module scope. They are imported inside the
# autouse fixture bodies that use them so each xdist worker pays the cold-import cost
# only when a test actually requires those fixtures. tests/unit/conftest.py overrides
# those autouse fixtures with no-ops, so unit-tier workers pay zero cost.
# Per software-development/policy/test-resource-discipline rule 17.
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


def pytest_collection_modifyitems(config, items):
    """Set per-marker timeouts: unit=1s, functional/integration=5s."""
    for item in items:
        if item.get_closest_marker("timeout") is not None:
            continue
        item_path = Path(str(item.path)).resolve()
        try:
            rel_path = item_path.relative_to(_repo_root)
        except ValueError:
            rel_path = item_path
        # These tests run the real SQLite schema and migration chain in fixture setup.
        if rel_path.parts[:4] == ("tests", "unit", "core", "db"):
            item.add_marker(pytest.mark.timeout(5))
            continue
        if "unit" in item.keywords:
            item.add_marker(pytest.mark.timeout(1))
        elif "functional" in item.keywords:
            item.add_marker(pytest.mark.timeout(5))
        elif "integration" in item.keywords:
            item.add_marker(pytest.mark.timeout(5))


def pytest_xdist_auto_num_workers(config):
    """Use half the available CPU cores for parallel test workers."""
    if config.option.numprocesses == "auto":
        try:
            cores = multiprocessing.cpu_count()
        except Exception:
            cores = 4
        return max(1, cores // 2)
    return None


# ---------------------------------------------------------------------------
# In-flight tracker + session-timeout diagnostic.
# Per software-development/policy/test-resource-discipline rules 14-15.
# Each worker writes its currently-running test's nodeid + monotonic start time
# to ${TMPDIR}/teleclaude_pytest_worker_<pid>.json during setup, clears it
# during teardown. The master watchdog (teleclaude/quality/test_watchdog.py) and
# the sessionfinish/keyboard_interrupt hooks read those files to name the hang.


# Platform detection done once per worker. macOS has no /proc, so we cache a
# psutil.Process handle and reuse it across tests; otherwise per-call overhead
# would dominate the unit-tier per-test budget.
def _build_fd_counter() -> Callable[[], int]:
    """Return the cheapest fd-counter for this platform, resolved once per worker."""
    if Path("/proc/self/fd").is_dir():
        proc_fd = "/proc/self/fd"

        def _counter_linux() -> int:
            try:
                return len(os.listdir(proc_fd))
            except OSError:
                return 0

        return _counter_linux
    try:
        import psutil  # startup boundary

        process_handle = psutil.Process()

        def _counter_psutil() -> int:
            try:
                return process_handle.num_fds()
            except Exception:
                return 0

        return _counter_psutil
    except Exception:
        return lambda: 0


_fd_counter = _build_fd_counter()


def _count_fds() -> int:
    return _fd_counter()


def _current_event_loop() -> asyncio.AbstractEventLoop | None:
    """Return the current event loop without emitting Python 3.12's deprecation warning."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            loop = asyncio.get_event_loop_policy().get_event_loop()
    except (RuntimeError, NotImplementedError):
        return None
    if loop.is_closed():
        return None
    return loop


def _sweep_asyncio_tasks(item) -> None:
    """Cancel + gather any asyncio tasks left running by the test.

    Per ``software-development/policy/test-resource-discipline`` rule 8: every
    ``asyncio.Task`` created by a test must terminate before the test ends. If a
    test creates a task and forgets to await/cancel it, this sweeper catches it
    and fails the test by name.
    """
    loop = _current_event_loop()
    if loop is None:
        return
    pending = [t for t in asyncio.all_tasks(loop) if not t.done()]
    if not pending:
        return
    for task in pending:
        task.cancel()
    try:
        loop.run_until_complete(asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=0.5))
    except (TimeoutError, RuntimeError):
        pass
    survivors = [t for t in pending if not t.done()]
    if survivors:
        names = ", ".join(t.get_name() for t in survivors)
        pytest.fail(f"Asyncio task leak: {len(survivors)} task(s) survived cancel in {item.nodeid}: {names}")


# Per-test instrumentation switches. The watchdog + inflight tracker are
# always on (they're the load-bearing diagnostic for hangs). FD-delta and the
# asyncio task sweep can be enabled per-environment via env vars when the
# leak-hunt campaign is active; otherwise they stay off to keep per-test
# overhead inside rule 15's budget.
_FD_DELTA_ENABLED = os.environ.get("TELECLAUDE_TEST_FD_CHECK", "0") == "1"
_FD_DELTA_STRICT = os.environ.get("TELECLAUDE_TEST_FD_STRICT", "0") == "1"
_ASYNCIO_SWEEP_ENABLED = os.environ.get("TELECLAUDE_TEST_ASYNC_SWEEP", "0") == "1"


def pytest_runtest_setup(item):
    """Record the in-flight test for this worker (and fd count if enabled)."""
    _watchdog.write_inflight(item.nodeid, time.monotonic())
    if _FD_DELTA_ENABLED:
        item._fd_count_at_setup = _count_fds()


def pytest_runtest_teardown(item, nextitem):
    """Clear in-flight record, sweep asyncio tasks, check fd-delta (if enabled)."""
    _watchdog.clear_inflight()
    if _ASYNCIO_SWEEP_ENABLED:
        _sweep_asyncio_tasks(item)
    if _FD_DELTA_ENABLED:
        after = _count_fds()
        before = getattr(item, "_fd_count_at_setup", after)
        delta = after - before
        if delta > 0:
            tier = _watchdog.tier_for_nodeid(item.nodeid)
            msg = f"FD leak in {item.nodeid} (tier={tier}): opened {delta} file descriptor(s) without closing"
            if _FD_DELTA_STRICT and tier == "unit":
                pytest.fail(msg)
            else:
                warnings.warn(msg, stacklevel=2)


def _emit_inflight_diagnostic(label: str) -> None:
    """Print per-worker in-flight tests to stderr when the suite is interrupted."""
    records = _watchdog.read_all_inflight()
    now = time.monotonic()
    print("\n" + "=" * 72, file=sys.stderr)
    print(f"{label}: per-worker in-flight tests at interrupt", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    if not records:
        print("(no in-flight tests recorded — all workers were between tests)", file=sys.stderr)
    else:
        for rec in sorted(records, key=lambda r: r.started_monotonic):
            elapsed = now - rec.started_monotonic
            print(
                f"  worker pid={rec.worker_pid:>6}  tier={rec.tier:<11}  elapsed={elapsed:>6.2f}s  {rec.nodeid}",
                file=sys.stderr,
            )
    print("=" * 72 + "\n", file=sys.stderr)


def pytest_sessionfinish(session, exitstatus):
    """On interrupted session (xdist session_timeout, ^C), print in-flight diagnostic."""
    # exitstatus 2 == pytest.ExitCode.INTERRUPTED, but we don't import the enum to keep
    # this module dependency-light. session.shouldfail / shouldstop also signal an early stop.
    interrupted = exitstatus == 2 or getattr(session, "shouldfail", None) or getattr(session, "shouldstop", None)
    if interrupted:
        _emit_inflight_diagnostic("SESSION INTERRUPTED")


def pytest_keyboard_interrupt(excinfo):
    """Defensive duplicate of the diagnostic — some xdist paths fire this instead of sessionfinish."""
    _emit_inflight_diagnostic("KEYBOARD INTERRUPT")


@pytest.fixture(autouse=True)
def _reset_event_bus():
    """Ensure global event bus handlers do not leak across tests."""
    event_bus.clear()
    reset_command_service()
    yield
    event_bus.clear()
    reset_command_service()


@pytest.fixture
def cluster_event_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    """Configure EventBus Redis only for tests that exercise CLUSTER emit paths."""
    monkeypatch.setattr(event_bus, "_role", "pytest")
    monkeypatch.setattr(event_bus, "_redis", _ClusterEmitRedisFake())


@pytest.fixture(autouse=True)
def _isolate_tui_state(tmp_path: "Path", monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Isolate TUI sticky state from user ~/.teleclaude/tui_state.json."""
    from teleclaude.cli.tui import state_store  # startup boundary

    tui_state = tmp_path / "tui_state.json"
    monkeypatch.setattr(paths, "TUI_STATE_PATH", tui_state)
    monkeypatch.setattr(state_store, "TUI_STATE_PATH", tui_state)
    yield


@pytest.fixture(autouse=True)
def _isolate_test_environment(tmp_path: "Path", monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Provide a consistent, isolated test environment for parallel runs."""
    # Deferred imports per test-resource-discipline rule 17 — keeps worker cold-start
    # off the SQLAlchemy/greenlet/aiosqlite import chain for unit tests that no-op this fixture.
    from teleclaude.core import db as db_module  # startup boundary
    from teleclaude.core import session_cleanup, session_utils  # startup boundary

    project_root = tmp_path / "project"
    project_root.mkdir(parents=True, exist_ok=True)
    config_path = project_root / "teleclaude.yml"
    if not config_path.exists():
        config_path.write_text("business:\n  domains:\n    software-development: docs\n", encoding="utf-8")

    # Force teleclaude.yml lookups to use the test config.
    monkeypatch.setenv("TELECLAUDE_PROJECT_CONFIG_PATH", str(config_path))

    db_module.db.db_path = str(tc_paths.MAIN_DB_PATH)

    # Isolate session workspaces for polling-related cleanup and file storage.
    try:
        workspace_root = tmp_path / "workspace"
        monkeypatch.setattr(session_utils, "OUTPUT_DIR", workspace_root, raising=False)
        monkeypatch.setattr(session_cleanup, "OUTPUT_DIR", workspace_root, raising=False)
    except Exception:
        pass

    yield


@pytest.fixture(scope="session", autouse=True)
def _neutralize_launcher_binaries() -> "object":
    """Prevent any un-mocked subprocess call from executing real macOS launcher binaries.

    Session-scoped: the patched values are constants across all tests. Paying the
    monkeypatch + deferred import once per session (instead of once per test)
    closes a real per-test budget item per
    ``software-development/policy/test-resource-discipline`` rule 3.
    """
    # Deferred imports per test-resource-discipline rule 17.
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


# TUI Test Fixtures


def create_mock_session(
    session_id: str = "test-session-001",
    title: str = "Test Session",
    status: str = "active",
    computer: str = "test-computer",
    active_agent: str = "claude",
    thinking_mode: str = "slow",
    last_input: str | None = None,
    last_output_summary: str | None = None,
    last_activity: str | None = None,
) -> dict[str, object]:  # guard: loose-dict
    """Create mock session data for testing.

    Args:
        session_id: Session ID
        title: Session title
        status: Session status
        computer: Computer name
        active_agent: Active agent name
        thinking_mode: Thinking mode
        last_input: Last input text
        last_output_summary: Last output text
        last_activity: Last activity timestamp (ISO format)

    Returns:
        Session data dict
    """
    now = datetime.now(UTC).isoformat()
    return {
        "session_id": session_id,
        "title": title,
        "status": status,
        "computer": computer,
        "active_agent": active_agent,
        "thinking_mode": thinking_mode,
        "last_input_origin": "telegram",
        "project_path": "/test/path",
        "created_at": now,
        "last_activity": last_activity or now,
        "last_input": last_input,
        "last_output_summary": last_output_summary,
        "display_index": "1",
        "tmux_session_name": f"teleclaude-{session_id}",
    }


def create_mock_computer(
    name: str = "test-computer",
    status: str = "online",
) -> dict[str, object]:  # guard: loose-dict
    """Create mock computer data for testing.

    Args:
        name: Computer name
        status: Computer status

    Returns:
        Computer data dict
    """
    return {
        "name": name,
        "status": status,
        "user": "testuser",
        "host": "test.local",
    }


def create_mock_project(
    path: str = "/test/project",
    computer: str = "test-computer",
) -> dict[str, object]:  # guard: loose-dict
    """Create mock project data for testing.

    Args:
        path: Project path
        computer: Computer name

    Returns:
        Project data dict
    """
    return {
        "path": path,
        "computer": computer,
    }


class MockAPIClient:
    """Mock API client that can simulate push events."""

    def __init__(self) -> None:
        """Initialize mock API client."""
        self._event_handlers: list[Callable[[str, dict[str, object]], None]] = []  # guard: loose-dict
        self.sessions: list[dict[str, object]] = []  # guard: loose-dict
        self.projects: list[dict[str, object]] = []  # guard: loose-dict
        self.computers: list[dict[str, object]] = []  # guard: loose-dict

    def on_event(self, handler: Callable[[str, dict[str, object]], None]) -> None:  # guard: loose-dict
        """Register event handler (like real client).

        Args:
            handler: Event handler function
        """
        self._event_handlers.append(handler)

    def simulate_event(self, event: str, data: dict[str, object]) -> None:  # guard: loose-dict
        """Simulate a push event from backend.

        Args:
            event: Event type
            data: Event data
        """
        for handler in self._event_handlers:
            handler(event, data)

    def get_sessions(self) -> list[dict[str, object]]:  # guard: loose-dict
        """Return mock sessions.

        Returns:
            List of session dicts
        """
        return self.sessions

    async def create_session(
        self,
        computer: str | None = None,
        project_path: str | None = None,
        agent: str = "claude",
        thinking_mode: str = "slow",
        message: str | None = None,
    ) -> dict[str, object]:  # guard: loose-dict
        """Mock create session.

        Args:
            computer: Computer name
            project_path: Project directory
            agent: Agent name
            thinking_mode: Thinking mode
            message: Initial message

        Returns:
            Session creation result
        """
        return {
            "session_id": "new-session-001",
            "tmux_session_name": "teleclaude-new-session-001",
        }

    async def end_session(
        self,
        session_id: str,
        computer: str,
    ) -> bool:
        """Mock end session.

        Args:
            session_id: Session ID
            computer: Computer name

        Returns:
            Success status
        """
        return True
