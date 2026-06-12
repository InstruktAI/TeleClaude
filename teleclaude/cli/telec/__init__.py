"""telec: TUI client for TeleClaude."""

import os
import subprocess
import sys
import time as _t
from collections.abc import Callable

from instrukt_ai_logging import InstruktAILogger, get_logger

from teleclaude.cli.session_auth import read_current_session_email

# Re-export TUI runners
from teleclaude.cli.telec._run_tui import _run_tui, _run_tui_config_mode

# Re-export shared config proxy and constants
from teleclaude.cli.telec._shared import (
    TMUX_ENV_KEY,
    TUI_ENV_KEY,
    TUI_SESSION_NAME,
    _ConfigProxy,
    config,
)

# Re-export auth helpers
from teleclaude.cli.telec.auth import _resolve_command_auth, is_command_allowed

# Re-export help functions (light — kept top-level for completion + help fast paths)
from teleclaude.cli.telec.help import (
    _complete_flags,
    _complete_subcmd,
    _flag_matches,
    _flag_used,
    _handle_completion,
    _maybe_show_help,
    _print_completion,
    _print_flag,
    _usage,
    _usage_leaf,
    _usage_main,
    _usage_subcmd,
)

# Re-export surface symbols
from teleclaude.cli.telec.surface import (  # type: ignore[attr-defined]
    _H,
    CLI_SURFACE,
    HELP_SUBCOMMAND_EXPANSIONS,
    CommandAuth,
    CommandDef,
    Flag,
    TelecCommand,
)
from teleclaude.cli.tool_client import ToolAPIError
from teleclaude.constants import ENV_ENABLE, MAIN_MODULE
from teleclaude.logging_config import setup_logging
from teleclaude.runtime.environment import filter_tui_tmux_environment

# Handler modules (handlers.{auth_cmds,bugs,code,config,content,docs,events_signals,
# history,memories,misc,todo}) and tool_commands are lazy-loaded inside
# the dispatch path. Eager loading drags in the OpenAI/Anthropic SDKs, the
# summarizer, the mirrors DB, and the todos DB — ~800ms — for every CLI call,
# including pre-commit lint steps that touch none of them.

# Handler modules (handlers.{auth_cmds,bugs,code,config,content,docs,events_signals,
# history,memories,misc,todo}) and tool_commands are lazy-loaded inside
# the dispatch path. Eager loading drags in the OpenAI/Anthropic SDKs, the
# summarizer, the mirrors DB, and the todos DB — ~800ms — for every CLI call,
# including pre-commit lint steps that touch none of them.

_BOOT = _t.monotonic()
_CLI_RUNTIME_FAILURES = (LookupError, OSError, RuntimeError, TypeError, ValueError)

__all__ = [
    "CLI_SURFACE",
    "HELP_SUBCOMMAND_EXPANSIONS",
    "TMUX_ENV_KEY",
    "TUI_ENV_KEY",
    "TUI_SESSION_NAME",
    "_H",
    "CommandAuth",
    "CommandDef",
    "Flag",
    "TelecCommand",
    "_ConfigProxy",
    "_complete_flags",
    "_complete_subcmd",
    "_flag_matches",
    "_flag_used",
    "_handle_completion",
    "_maybe_show_help",
    "_print_completion",
    "_print_flag",
    "_resolve_command_auth",
    "_run_tui",
    "_run_tui_config_mode",
    "_usage",
    "_usage_leaf",
    "_usage_main",
    "_usage_subcmd",
    "config",
    "is_command_allowed",
    "main",
]


def main() -> None:
    """Main entry point for telec CLI."""
    # Handle shell completion before any other setup
    if os.environ.get("TELEC_COMPLETE"):
        _handle_completion()
        return

    setup_logging()
    logger = get_logger(__name__)
    logger.trace("[PERF] main() imports done dt=%.3f", _t.monotonic() - _BOOT)
    argv = sys.argv[1:]

    # Handle --help / -h
    if argv and argv[0] in ("--help", "-h"):
        print(_usage())
        return

    if argv:
        try:
            _handle_cli_argv(argv)
        except ToolAPIError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        return

    _start_tui(logger)


def _handle_cli_command(argv: list[str]) -> None:
    """Handle CLI shortcuts like /list, /claude, etc.

    Args:
        argv: Command-line arguments
    """
    cmd = argv[0].lstrip("/")
    args = argv[1:]

    # Centralized -h handling for all commands
    if _maybe_show_help(cmd, args):
        return

    try:
        cmd_enum = TelecCommand(cmd)
    except ValueError:
        cmd_enum = None

    cmd_def = CLI_SURFACE.get(cmd)
    if cmd_def and cmd_def.subcommands and not cmd_def.standalone and not args:
        print(_usage(cmd))
        return

    handler = _resolve_cli_handler(cmd_enum, args)
    if handler is None:
        print(f"Unknown command: /{cmd}")
        print(_usage())
        return
    handler()


def _handle_cli_argv(argv: list[str]) -> None:
    token = argv[0].lstrip("/")
    if token in {cmd.value for cmd in TelecCommand} or argv[0].startswith("/"):
        _handle_cli_command(argv)
        return
    print(f"Unknown command: {argv[0]}")
    print(_usage())
    raise SystemExit(1)


def _start_tui(logger: InstruktAILogger) -> None:
    if not os.environ.get(TMUX_ENV_KEY):
        _exec_tmux_tui()
        return

    try:
        _run_tui()
    except KeyboardInterrupt:
        pass  # Clean exit on Ctrl-C
    except _CLI_RUNTIME_FAILURES:
        logger.exception("telec TUI crashed during startup")


def _exec_tmux_tui() -> None:
    from teleclaude.cli.telec.handlers.auth_cmds import _requires_tui_login

    terminal_email = read_current_session_email()
    if _requires_tui_login() and not terminal_email:
        print("Error: telec auth login is required before starting the TUI in multi-user mode.")
        print("Run: telec auth login <email>")
        raise SystemExit(1)

    tmux = config.computer.tmux_binary
    result = subprocess.run(
        [tmux, "has-session", "-t", TUI_SESSION_NAME],
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        subprocess.run(
            [tmux, "kill-session", "-t", TUI_SESSION_NAME],
            check=False,
            capture_output=True,
        )

    tui_env = filter_tui_tmux_environment(os.environ)
    tui_env[TUI_ENV_KEY] = ENV_ENABLE
    tmux_args = [tmux, "new-session", "-s", TUI_SESSION_NAME]
    for key, value in tui_env.items():
        tmux_args.extend(["-e", f"{key}={value}"])
    tmux_args.append("telec")
    os.execlp(tmux, *tmux_args)


def _resolve_cli_handler(cmd_enum: TelecCommand | None, args: list[str]) -> Callable[[], None] | None:
    def _lazy(module: str, attr: str, *, pass_args: bool = True) -> Callable[[], None]:
        def _call() -> None:
            from importlib import import_module

            fn = getattr(import_module(module), attr)
            fn(args) if pass_args else fn()

        return _call

    def handle_sessions_command() -> None:
        if args and args[0] == "revive":
            from teleclaude.cli.telec.handlers.misc import _handle_revive

            _handle_revive(args[1:])
            return
        from teleclaude.cli.tool_commands import handle_sessions

        handle_sessions(args)

    handlers: dict[TelecCommand, Callable[[], None]] = {
        TelecCommand.SESSIONS: handle_sessions_command,
        TelecCommand.COMPUTERS: _lazy("teleclaude.cli.telec.handlers.misc", "_handle_computers"),
        TelecCommand.PROJECTS: _lazy("teleclaude.cli.telec.handlers.misc", "_handle_projects"),
        TelecCommand.AGENTS: _lazy("teleclaude.cli.tool_commands", "handle_agents"),
        TelecCommand.CHANNELS: _lazy("teleclaude.cli.tool_commands", "handle_channels"),
        TelecCommand.OPERATIONS: _lazy("teleclaude.cli.tool_commands", "handle_operations"),
        TelecCommand.VERSION: _lazy("teleclaude.cli.telec.handlers.misc", "_handle_version", pass_args=False),
        TelecCommand.SYNC: _lazy("teleclaude.cli.telec.handlers.misc", "_handle_sync"),
        TelecCommand.DOCS: _lazy("teleclaude.cli.telec.handlers.docs", "_handle_docs"),
        TelecCommand.TODO: _lazy("teleclaude.cli.telec.handlers.todo", "_handle_todo"),
        TelecCommand.BUGS: _lazy("teleclaude.cli.telec.handlers.bugs", "_handle_bugs"),
        TelecCommand.EVENTS: _lazy("teleclaude.cli.telec.handlers.events_signals", "_handle_events"),
        TelecCommand.AUTH: _lazy("teleclaude.cli.telec.handlers.auth_cmds", "_handle_auth"),
        TelecCommand.CONFIG: _lazy("teleclaude.cli.telec.handlers.config", "_handle_config"),
        TelecCommand.CONTENT: _lazy("teleclaude.cli.telec.handlers.content", "_handle_content"),
        TelecCommand.HISTORY: _lazy("teleclaude.cli.telec.handlers.history", "_handle_history"),
        TelecCommand.MEMORIES: _lazy("teleclaude.cli.telec.handlers.memories", "_handle_memories"),
        TelecCommand.SIGNALS: _lazy("teleclaude.cli.telec.handlers.events_signals", "_handle_signals"),
        TelecCommand.CODE: _lazy("teleclaude.cli.telec.handlers.code", "handle_code"),
        TelecCommand.CONTEXT: _lazy("teleclaude.cli.telec.handlers.context", "_handle_context"),
    }
    if cmd_enum is None:
        return None
    return handlers.get(cmd_enum)


if __name__ == MAIN_MODULE:
    main()
