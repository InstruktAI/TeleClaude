"""TUI run helpers — split out to avoid circular imports from config handler."""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import time as _t
from typing import Any

from teleclaude.cli.session_auth import TUI_CARRIED_IDENTITY_ENV_KEY, read_current_session_email
from teleclaude.cli.telec._shared import TMUX_ENV_KEY, TUI_ENV_KEY, TUI_SESSION_NAME
from teleclaude.cli.tui.processes import deregister_tui
from teleclaude.config.machine import config
from teleclaude.constants import ENV_ENABLE
from teleclaude.project_root import resolve_invocation_roots
from teleclaude.runtime.environment import filter_tui_tmux_environment

__all__ = [
    "_run_tui",
    "_run_tui_config_mode",
    "start_tui",
]

_TUI_FAILURES = (LookupError, OSError, RuntimeError, TypeError, ValueError)


def start_tui() -> None:
    """Launch the TUI, creating its tmux session when invoked outside tmux."""
    logger = importlib.import_module("instrukt_ai_logging").get_logger(__name__)
    if not os.environ.get(TMUX_ENV_KEY):  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
        _exec_tmux_tui()
        return
    try:
        _run_tui()
    except KeyboardInterrupt:
        pass
    except _TUI_FAILURES:
        logger.exception("telec TUI crashed during startup")


def _exec_tmux_tui() -> None:
    invocation_dir = resolve_invocation_roots().invocation_dir
    terminal_email = read_current_session_email()

    tmux = config.computer.tmux_binary
    result = subprocess.run([tmux, "has-session", "-t", TUI_SESSION_NAME], capture_output=True, check=False)
    if result.returncode == 0:
        subprocess.run(
            [tmux, "kill-session", "-t", TUI_SESSION_NAME],
            check=False,
            capture_output=True,
        )
    tui_env = filter_tui_tmux_environment(os.environ)  # fmt: skip  # guard: direct-env-read - allowed: child-process environment construction
    tui_env[TUI_ENV_KEY] = ENV_ENABLE
    if terminal_email:
        tui_env[TUI_CARRIED_IDENTITY_ENV_KEY] = terminal_email
    # Start the pane where the next wrapper can recapture the caller's directory.
    tmux_args = [tmux, "new-session", "-s", TUI_SESSION_NAME, "-c", str(invocation_dir)]
    for key, value in tui_env.items():
        tmux_args.extend(["-e", f"{key}={value}"])
    tmux_args.append("telec")
    os.execlp(tmux, *tmux_args)


def _load_tui_runtime() -> tuple[Any, ...]:
    logger = importlib.import_module("instrukt_ai_logging").get_logger(__name__)
    api_client = importlib.import_module("teleclaude.cli.api_client").TelecAPIClient
    misc = importlib.import_module("teleclaude.cli.telec.handlers.misc")
    app_module = importlib.import_module("teleclaude.cli.tui.app")
    ensure_tmux_mouse_on = misc._ensure_tmux_mouse_on
    ensure_tmux_status_hidden_for_tui = misc._ensure_tmux_status_hidden_for_tui
    maybe_kill_tui_session = misc._maybe_kill_tui_session
    return (
        logger,
        api_client,
        ensure_tmux_mouse_on,
        ensure_tmux_status_hidden_for_tui,
        maybe_kill_tui_session,
        app_module.RELOAD_EXIT,
        app_module.TelecApp,
    )


def _resolve_reload_exec_argv() -> tuple[str, list[str]]:
    entrypoint = sys.argv[0]
    if (
        entrypoint
        and os.path.isabs(entrypoint)
        and os.path.basename(entrypoint) == "telec"
        and os.access(entrypoint, os.X_OK)
    ):
        return entrypoint, [entrypoint]

    telec_entrypoint = shutil.which("telec")
    if telec_entrypoint:
        return telec_entrypoint, [telec_entrypoint]

    python = sys.executable
    return python, [python, "-m", "teleclaude.cli.telec"]


def _run_tui(start_view: int = 1, config_guided: bool = False) -> None:
    """Run TUI application.

    On SIGUSR2 the app exits with RELOAD_EXIT. We skip tmux session
    cleanup and os.execvp to restart the process, reloading all Python
    modules from disk.
    """
    _t0 = _t.monotonic()
    (
        logger,
        api_client,
        ensure_tmux_mouse_on,
        ensure_tmux_status_hidden_for_tui,
        maybe_kill_tui_session,
        reload_exit,
        telec_app,
    ) = _load_tui_runtime()

    logger.trace("[PERF] _run_tui import TelecApp dt=%.3f", _t.monotonic() - _t0)
    api = api_client()
    app = telec_app(api, start_view=start_view, config_guided=config_guided)
    logger.trace("[PERF] _run_tui TelecApp created dt=%.3f", _t.monotonic() - _t0)

    reload_requested = False

    try:
        ensure_tmux_status_hidden_for_tui()
        ensure_tmux_mouse_on()
        logger.trace("[PERF] _run_tui pre-app.run dt=%.3f", _t.monotonic() - _t0)
        reload_requested = app.run() == reload_exit
    except KeyboardInterrupt:
        pass  # Clean exit on Ctrl-C
    except _TUI_FAILURES:
        logger.exception("telec TUI crashed")
    finally:
        # Withdrawn on every exit, reload included: the exec hands this pid to
        # the launch wrapper, which outlives the handoff and answers no signal,
        # while the TUI comes back as that wrapper's child under a new pid and
        # records itself then.
        deregister_tui(os.getpid())
        if not reload_requested:
            maybe_kill_tui_session()

    if reload_requested:
        # Mark as reload so the new process skips re-applying pane layout.
        os.environ["TELEC_RELOAD"] = "1"  # fmt: skip  # guard: direct-env-read - allowed: bootstrap or internal process signal
        executable, argv = _resolve_reload_exec_argv()
        # The wrapper recaptures its invocation directory from the process cwd.
        os.chdir(resolve_invocation_roots().invocation_dir)
        os.execvp(executable, argv)


def _run_tui_config_mode(guided: bool = False) -> None:
    """Run TUI in configuration mode."""
    _run_tui(start_view=4, config_guided=guided)
