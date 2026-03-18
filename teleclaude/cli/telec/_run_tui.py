"""TUI run helpers — split out to avoid circular imports from config handler."""

from __future__ import annotations

import importlib
import os
import sys
import time as _t

__all__ = [
    "_run_tui",
    "_run_tui_config_mode",
]

_TUI_FAILURES = (LookupError, OSError, RuntimeError, TypeError, ValueError)


def _load_tui_runtime():
    logger = importlib.import_module("instrukt_ai_logging").get_logger(__name__)
    api_client = importlib.import_module("teleclaude.cli.api_client").TelecAPIClient
    misc = importlib.import_module("teleclaude.cli.telec.handlers.misc")
    app_module = importlib.import_module("teleclaude.cli.tui.app")
    return (
        logger,
        api_client,
        misc._ensure_tmux_mouse_on,
        misc._ensure_tmux_status_hidden_for_tui,
        misc._maybe_kill_tui_session,
        app_module.RELOAD_EXIT,
        app_module.TelecApp,
    )


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
        if not reload_requested:
            maybe_kill_tui_session()

    if reload_requested:
        # Re-exec via the Python interpreter + module flag, not sys.argv[0]
        # (which may be a .py file path without execute permission).
        # Mark as reload so the new process skips re-applying pane layout.
        os.environ["TELEC_RELOAD"] = "1"
        python = sys.executable
        os.execvp(python, [python, "-m", "teleclaude.cli.telec"])


def _run_tui_config_mode(guided: bool = False) -> None:
    """Run TUI in configuration mode."""
    _run_tui(start_view=4, config_guided=guided)
