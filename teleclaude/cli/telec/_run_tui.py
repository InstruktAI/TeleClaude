"""TUI run helpers — split out to avoid circular imports from config handler."""
from __future__ import annotations

import os
import sys
import time as _t



__all__ = [
    "_run_tui",
    "_run_tui_config_mode",
]

def _run_tui(start_view: int = 1, config_guided: bool = False) -> None:
    """Run TUI application.

    On SIGUSR2 the app exits with RELOAD_EXIT. We skip tmux session
    cleanup and os.execvp to restart the process, reloading all Python
    modules from disk.
    """
    from instrukt_ai_logging import get_logger

    logger = get_logger(__name__)
    _t0 = _t.monotonic()
    from teleclaude.cli.api_client import TelecAPIClient
    from teleclaude.cli.telec.handlers.misc import (
        _ensure_tmux_mouse_on,
        _ensure_tmux_status_hidden_for_tui,
        _maybe_kill_tui_session,
    )
    from teleclaude.cli.tui.app import RELOAD_EXIT, TelecApp

    logger.trace("[PERF] _run_tui import TelecApp dt=%.3f", _t.monotonic() - _t0)
    api = TelecAPIClient()
    app = TelecApp(api, start_view=start_view, config_guided=config_guided)
    logger.trace("[PERF] _run_tui TelecApp created dt=%.3f", _t.monotonic() - _t0)

    reload_requested = False

    try:
        _ensure_tmux_status_hidden_for_tui()
        _ensure_tmux_mouse_on()
        logger.trace("[PERF] _run_tui pre-app.run dt=%.3f", _t.monotonic() - _t0)
        result = app.run()
        reload_requested = result == RELOAD_EXIT
    except KeyboardInterrupt:
        pass  # Clean exit on Ctrl-C
    except Exception:
        logger.exception("telec TUI crashed")
    finally:
        if not reload_requested:
            _maybe_kill_tui_session()

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
