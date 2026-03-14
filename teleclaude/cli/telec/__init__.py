"""telec: TUI client for TeleClaude."""

import os
import subprocess
import sys
import time as _t
from collections.abc import Callable
from pathlib import Path

_BOOT = _t.monotonic()

from instrukt_ai_logging import get_logger

from teleclaude.cli.session_auth import read_current_session_email

# Re-export TUI runners
from teleclaude.cli.telec._run_tui import _run_tui, _run_tui_config_mode

# Re-export shared config proxy and constants
from teleclaude.cli.telec._shared import (
    TMUX_ENV_KEY,
    TUI_AUTH_EMAIL_ENV_KEY,
    TUI_ENV_KEY,
    TUI_SESSION_NAME,
    _ConfigProxy,
    config,
)

# Re-export auth helpers
from teleclaude.cli.telec.auth import _resolve_command_auth, is_command_allowed
from teleclaude.cli.telec.handlers.auth_cmds import (
    _handle_auth,
    _handle_login,
    _handle_logout,
    _handle_whoami,
    _requires_tui_login,
    _role_for_email,
)
from teleclaude.cli.telec.handlers.bugs import (
    _handle_bugs,
    _handle_bugs_create,
    _handle_bugs_list,
    _handle_bugs_report,
)
from teleclaude.cli.telec.handlers.config import _handle_config
from teleclaude.cli.telec.handlers.content import _handle_content, _handle_content_dump
from teleclaude.cli.telec.handlers.demo import (
    _check_no_demo_marker,
    _demo_create,
    _demo_list,
    _demo_run,
    _demo_validate,
    _extract_demo_blocks,
    _find_demo_md,
    _handle_todo_demo,
)
from teleclaude.cli.telec.handlers.docs import _handle_docs, _handle_docs_get, _handle_docs_index
from teleclaude.cli.telec.handlers.events_signals import (
    _handle_events,
    _handle_events_list,
    _handle_signals,
    _handle_signals_status,
)
from teleclaude.cli.telec.handlers.history import (
    _handle_history,
    _handle_history_search,
    _handle_history_show,
)
from teleclaude.cli.telec.handlers.memories import (
    _VALID_OBS_TYPES,
    _handle_memories,
    _handle_memories_delete,
    _handle_memories_save,
    _handle_memories_search,
    _handle_memories_timeline,
)

# Re-export handlers
from teleclaude.cli.telec.handlers.misc import (
    _attach_tmux_session,
    _ensure_tmux_mouse_on,
    _ensure_tmux_status_hidden_for_tui,
    _git_short_commit_hash,
    _handle_computers,
    _handle_projects,
    _handle_revive,
    _handle_sync,
    _handle_version,
    _handle_watch,
    _maybe_kill_tui_session,
    _revive_session,
    _revive_session_via_api,
    _send_revive_enter_via_api,
)
from teleclaude.cli.telec.handlers.roadmap import (
    _handle_roadmap,
    _handle_roadmap_add,
    _handle_roadmap_deliver,
    _handle_roadmap_deps,
    _handle_roadmap_freeze,
    _handle_roadmap_migrate_icebox,
    _handle_roadmap_move,
    _handle_roadmap_remove,
    _handle_roadmap_show,
    _handle_roadmap_unfreeze,
)
from teleclaude.cli.telec.handlers.todo import (
    _handle_todo,
    _handle_todo_create,
    _handle_todo_dump,
    _handle_todo_remove,
    _handle_todo_split,
    _handle_todo_validate,
    _handle_todo_verify_artifacts,
)

# Re-export help functions
from teleclaude.cli.telec.help import (
    _complete_flags,
    _complete_subcmd,
    _example_commands,
    _example_positionals,
    _flag_matches,
    _flag_used,
    _handle_completion,
    _maybe_show_help,
    _print_completion,
    _print_flag,
    _sample_flag_value,
    _sample_positional_value,
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
from teleclaude.cli.tool_commands import (
    handle_agents,
    handle_channels,
    handle_operations,
    handle_sessions,
)
from teleclaude.constants import ENV_ENABLE, MAIN_MODULE
from teleclaude.logging_config import setup_logging
from teleclaude.project_setup import init_project

__all__ = [
    "CLI_SURFACE",
    "HELP_SUBCOMMAND_EXPANSIONS",
    "TMUX_ENV_KEY",
    "TUI_AUTH_EMAIL_ENV_KEY",
    "TUI_ENV_KEY",
    "TUI_SESSION_NAME",
    "_H",
    "_VALID_OBS_TYPES",
    "CommandAuth",
    "CommandDef",
    "Flag",
    "TelecCommand",
    "_ConfigProxy",
    "_attach_tmux_session",
    "_check_no_demo_marker",
    "_complete_flags",
    "_complete_subcmd",
    "_demo_create",
    "_demo_list",
    "_demo_run",
    "_demo_validate",
    "_ensure_tmux_mouse_on",
    "_ensure_tmux_status_hidden_for_tui",
    "_example_commands",
    "_example_positionals",
    "_extract_demo_blocks",
    "_find_demo_md",
    "_flag_matches",
    "_flag_used",
    "_git_short_commit_hash",
    "_handle_auth",
    "_handle_bugs",
    "_handle_bugs_create",
    "_handle_bugs_list",
    "_handle_bugs_report",
    "_handle_completion",
    "_handle_computers",
    "_handle_config",
    "_handle_content",
    "_handle_content_dump",
    "_handle_docs",
    "_handle_docs_get",
    "_handle_docs_index",
    "_handle_events",
    "_handle_events_list",
    "_handle_history",
    "_handle_history_search",
    "_handle_history_show",
    "_handle_login",
    "_handle_logout",
    "_handle_memories",
    "_handle_memories_delete",
    "_handle_memories_save",
    "_handle_memories_search",
    "_handle_memories_timeline",
    "_handle_projects",
    "_handle_revive",
    "_handle_roadmap",
    "_handle_roadmap_add",
    "_handle_roadmap_deliver",
    "_handle_roadmap_deps",
    "_handle_roadmap_freeze",
    "_handle_roadmap_migrate_icebox",
    "_handle_roadmap_move",
    "_handle_roadmap_remove",
    "_handle_roadmap_show",
    "_handle_roadmap_unfreeze",
    "_handle_signals",
    "_handle_signals_status",
    "_handle_sync",
    "_handle_todo",
    "_handle_todo_create",
    "_handle_todo_demo",
    "_handle_todo_dump",
    "_handle_todo_remove",
    "_handle_todo_split",
    "_handle_todo_validate",
    "_handle_todo_verify_artifacts",
    "_handle_version",
    "_handle_watch",
    "_handle_whoami",
    "_maybe_kill_tui_session",
    "_maybe_show_help",
    "_print_completion",
    "_print_flag",
    "_requires_tui_login",
    "_resolve_command_auth",
    "_revive_session",
    "_revive_session_via_api",
    "_role_for_email",
    "_run_tui",
    "_run_tui_config_mode",
    "_sample_flag_value",
    "_sample_positional_value",
    "_send_revive_enter_via_api",
    "_usage",
    "_usage_leaf",
    "_usage_main",
    "_usage_subcmd",
    "config",
    "is_command_allowed",
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
        token = argv[0].lstrip("/")
        if token in {cmd.value for cmd in TelecCommand}:
            _handle_cli_command(argv)
            return
        if argv[0].startswith("/"):
            _handle_cli_command(argv)
            return
        print(f"Unknown command: {argv[0]}")
        print(_usage())
        raise SystemExit(1)

    # TUI mode - ensure we're in tmux for pane preview
    if not os.environ.get(TMUX_ENV_KEY):
        # Bridge outer-shell login identity into the trusted tc_tui session.
        terminal_email = read_current_session_email()
        if _requires_tui_login() and not terminal_email:
            print("Error: telec auth login is required before starting the TUI in multi-user mode.")
            print("Run: telec auth login <email>")
            raise SystemExit(1)
        # Always restart the TUI session to avoid adopting stale panes
        tmux = config.computer.tmux_binary
        result = subprocess.run(
            [tmux, "has-session", "-t", TUI_SESSION_NAME],
            capture_output=True,
        )
        if result.returncode == 0:
            subprocess.run(
                [tmux, "kill-session", "-t", TUI_SESSION_NAME],
                check=False,
                capture_output=True,
            )
        # Create new named session and mark it as telec-managed
        tmux_args = [tmux, "new-session", "-s", TUI_SESSION_NAME, "-e", f"{TUI_ENV_KEY}={ENV_ENABLE}"]
        if terminal_email:
            tmux_args.extend(["-e", f"{TUI_AUTH_EMAIL_ENV_KEY}={terminal_email}"])
        for key, value in os.environ.items():
            if key in {TUI_ENV_KEY, TUI_AUTH_EMAIL_ENV_KEY}:
                continue
            tmux_args.extend(["-e", f"{key}={value}"])
        tmux_args.append("telec")
        os.execlp(tmux, *tmux_args)

    try:
        _run_tui()
    except KeyboardInterrupt:
        pass  # Clean exit on Ctrl-C
    except Exception:
        logger.exception("telec TUI crashed during startup")


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


def _resolve_cli_handler(cmd_enum: TelecCommand | None, args: list[str]) -> Callable[[], None] | None:
    def handle_sessions_command() -> None:
        if args and args[0] == "revive":
            _handle_revive(args[1:])
            return
        handle_sessions(args)

    handlers = {
        TelecCommand.SESSIONS: handle_sessions_command,
        TelecCommand.COMPUTERS: lambda: _handle_computers(args),
        TelecCommand.PROJECTS: lambda: _handle_projects(args),
        TelecCommand.AGENTS: lambda: handle_agents(args),
        TelecCommand.CHANNELS: lambda: handle_channels(args),
        TelecCommand.OPERATIONS: lambda: handle_operations(args),
        TelecCommand.INIT: lambda: init_project(Path.cwd()),
        TelecCommand.VERSION: _handle_version,
        TelecCommand.SYNC: lambda: _handle_sync(args),
        TelecCommand.WATCH: lambda: _handle_watch(args),
        TelecCommand.DOCS: lambda: _handle_docs(args),
        TelecCommand.TODO: lambda: _handle_todo(args),
        TelecCommand.ROADMAP: lambda: _handle_roadmap(args),
        TelecCommand.BUGS: lambda: _handle_bugs(args),
        TelecCommand.EVENTS: lambda: _handle_events(args),
        TelecCommand.AUTH: lambda: _handle_auth(args),
        TelecCommand.CONFIG: lambda: _handle_config(args),
        TelecCommand.CONTENT: lambda: _handle_content(args),
        TelecCommand.HISTORY: lambda: _handle_history(args),
        TelecCommand.MEMORIES: lambda: _handle_memories(args),
        TelecCommand.SIGNALS: lambda: _handle_signals(args),
    }
    return handlers.get(cmd_enum)


if __name__ == MAIN_MODULE:
    main()
