"""telec: TUI client for TeleClaude."""

import importlib
import os
import sys
from collections.abc import Callable

from teleclaude.cli.session_auth import require_cli_clearance
from teleclaude.cli.telec.handlers._arg_parsing import CliUsageError, parse_command_args
from teleclaude.cli.telec.help import (
    _handle_completion,
    _maybe_show_help,
    _resolve_command_path,
    _usage,
    _usage_resolved,
)
from teleclaude.cli.telec.surface import (
    CLI_SURFACE,
    SESSIONS_END,
    SESSIONS_RESTART,
    CommandDef,
    TelecCommand,
)
from teleclaude.constants import MAIN_MODULE

from . import flags as F

_INVALID_CONFIGURATION_ERROR = "Error: invalid configuration.\n%s"

__all__ = ["main"]


def main() -> None:
    """Main entry point for telec CLI."""
    # Handle shell completion before any other setup
    if os.environ.get("TELEC_COMPLETE"):  # fmt: skip  # guard: direct-env-read - allowed: bootstrap or internal process signal
        _handle_completion()
        return

    argv = sys.argv[1:]

    # Handle --help / -h
    if argv and argv[0] in ("--help", "-h"):
        print(_usage())
        return

    if argv:
        _handle_cli_argv(argv)
        return

    _start_tui()


def _resolve_and_enforce(cmd: str, args: list[str]) -> tuple[list[str], CommandDef, list[str]]:
    """Resolve the leaf ``CommandDef`` for ``cmd``/``args`` and enforce its
    declared-option policy over the unconsumed remainder — dispatch-free.

    Returns ``(path, node, remainder)``. Raises ``CliUsageError`` on an
    unknown option, a missing value, or a value given to a switch; the
    caller renders the message against the returned node's usage. The
    parsed result itself is not returned — a handler that needs option
    values calls ``parse_command_args`` again against the same node.
    """
    path, node = _resolve_command_path(cmd, args)
    remainder = args[len(path) - 1 :]
    parse_command_args(node, remainder)
    return path, node, remainder


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
    if cmd_def is None:
        print(f"Unknown command: /{cmd}")
        print(_usage())
        return
    if cmd_def and cmd_def.subcommands and not cmd_def.standalone and not args:
        print(_usage(cmd))
        return

    try:
        path, node, remainder = _resolve_and_enforce(cmd, args)
    except CliUsageError as exc:
        path, node = _resolve_command_path(cmd, args)
        print(str(exc), file=sys.stderr)
        print(_usage_resolved(path, node), file=sys.stderr)
        raise SystemExit(1) from exc

    target_session_id = _session_action_target(node, remainder)
    command_path = " ".join(path)
    require_cli_clearance(command_path, target_session_id, node.auth)

    handler = _resolve_cli_handler(cmd_enum, args)
    if handler is None:
        print(f"Unknown command: /{cmd}")
        print(_usage())
        return
    _dispatch_handler(handler)


def _handle_cli_argv(argv: list[str]) -> None:
    token = argv[0].lstrip("/")
    if token in {cmd.value for cmd in TelecCommand} or argv[0].startswith("/"):
        _handle_cli_command(argv)
        return
    print(f"Unknown command: {argv[0]}")
    print(_usage())
    raise SystemExit(1)


def _start_tui() -> None:
    tui = importlib.import_module("teleclaude.cli.telec._run_tui")
    tui.start_tui()


def _session_action_target(node: CommandDef, args: list[str]) -> str | None:
    if node is SESSIONS_END:
        parsed = parse_command_args(node, args)
        return parsed.positionals[0] if parsed.positionals else parsed.value(F.FLAG_SESSION)
    if node is SESSIONS_RESTART:
        parsed = parse_command_args(node, args)
        return parsed.positionals[0] if parsed.positionals else None
    return None


def _dispatch_handler(handler: Callable[[], None]) -> None:
    importlib.import_module("teleclaude.logging_config").setup_logging()
    try:
        handler()
    except Exception as exc:
        if _is_loaded_exception(exc, "teleclaude.cli.tool_client", "ToolAPIError"):
            print(f"Error: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        if _is_loaded_exception(exc, "pydantic", "ValidationError"):
            print(_INVALID_CONFIGURATION_ERROR % exc, file=sys.stderr)
            raise SystemExit(1) from exc
        raise


def _is_loaded_exception(error: Exception, module_name: str, exception_name: str) -> bool:
    module = sys.modules.get(module_name)
    if module is None:
        return False
    exception_type = getattr(module, exception_name, None)
    return (
        isinstance(exception_type, type)
        and issubclass(exception_type, BaseException)
        and isinstance(error, exception_type)
    )


def _resolve_cli_handler(cmd_enum: TelecCommand | None, args: list[str]) -> Callable[[], None] | None:
    def _lazy(module: str, attr: str, *, pass_args: bool = True) -> Callable[[], None]:
        def _call() -> None:
            fn = getattr(importlib.import_module(module), attr)
            fn(args) if pass_args else fn()

        return _call

    def handle_sessions_command() -> None:
        if args and args[0] == "revive":
            revive_handler = importlib.import_module("teleclaude.cli.telec.handlers.misc")._handle_revive
            revive_handler(args[1:])
            return
        importlib.import_module("teleclaude.cli.tool_commands.sessions").handle_sessions(args)

    handlers: dict[TelecCommand, Callable[[], None]] = {
        TelecCommand.SESSIONS: handle_sessions_command,
        TelecCommand.REMINDERS: _lazy("teleclaude.cli.tool_commands.reminders", "handle_reminders"),
        TelecCommand.COMPUTERS: _lazy("teleclaude.cli.telec.handlers.misc", "_handle_computers"),
        TelecCommand.PROJECTS: _lazy("teleclaude.cli.telec.handlers.misc", "_handle_projects"),
        TelecCommand.AGENTS: _lazy("teleclaude.cli.tool_commands", "handle_agents"),
        TelecCommand.CHANNELS: _lazy("teleclaude.cli.tool_commands", "handle_channels"),
        TelecCommand.OPERATIONS: _lazy("teleclaude.cli.tool_commands", "handle_operations"),
        TelecCommand.VERSION: _lazy("teleclaude.cli.telec.handlers.misc", "_handle_version", pass_args=False),
        TelecCommand.DOCS: _lazy("teleclaude.cli.telec.handlers.docs", "_handle_docs"),
        TelecCommand.TODO: _lazy("teleclaude.cli.telec.handlers.todo", "_handle_todo"),
        TelecCommand.BUGS: _lazy("teleclaude.cli.telec.handlers.bugs", "_handle_bugs"),
        TelecCommand.JOBS: _lazy("teleclaude.cli.tool_commands.jobs", "handle_jobs"),
        TelecCommand.EVENTS: _lazy("teleclaude.cli.telec.handlers.events_signals", "_handle_events"),
        TelecCommand.AUTH: _lazy("teleclaude.cli.telec.handlers.auth_cmds", "_handle_auth"),
        TelecCommand.CONFIG: _lazy("teleclaude.cli.telec.handlers.config", "_handle_config"),
        TelecCommand.CONTENT: _lazy("teleclaude.cli.telec.handlers.content", "_handle_content"),
        TelecCommand.HISTORY: _lazy("teleclaude.cli.telec.handlers.history", "_handle_history"),
        TelecCommand.MEMORIES: _lazy("teleclaude.cli.telec.handlers.memories", "_handle_memories"),
        TelecCommand.SIGNALS: _lazy("teleclaude.cli.telec.handlers.events_signals", "_handle_signals"),
        TelecCommand.MCP: _lazy("teleclaude.cli.telec.handlers.mcp", "_handle_mcp"),
        TelecCommand.CODE: _lazy("teleclaude.cli.telec.handlers.code", "handle_code"),
        TelecCommand.MESSAGE: _lazy("teleclaude.cli.telec.handlers.message", "_handle_message"),
    }
    if cmd_enum is None:
        return None
    return handlers.get(cmd_enum)


if __name__ == MAIN_MODULE:
    main()
