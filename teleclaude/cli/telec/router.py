"""The telec router: resolve a command, answer help and usage, and dispatch its handler after clearance."""

import importlib
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from teleclaude.cli import CommandScope
from teleclaude.cli.telec.handlers._arg_parsing import (
    CliUsageError,
    ParsedArgs,
    parse_command_args,
    without_value_flag,
)
from teleclaude.cli.telec.help import (
    _handle_completion,
    _maybe_show_help,
    _resolve_command_path,
    _usage,
    _usage_resolved,
)
from teleclaude.cli.telec.surface import (
    CLI_SURFACE,
    CommandAuth,
    CommandDef,
    TelecCommand,
)
from teleclaude.cli.telec.surface_types import admits_any_caller

from . import flags as F

if TYPE_CHECKING:
    from teleclaude.cli.tool_client import ToolAPIError

# The alias value is evaluated lazily, so naming the type here loads nothing at startup.
type _ToolAPIError = ToolAPIError

_INVALID_CONFIGURATION_ERROR = "Error: invalid configuration.\n%s"
_LOGGING_MODULE = "teleclaude.logging_config"
_AUDIO_HANDLER_MODULE = "teleclaude.cli.telec.handlers.audio"
_AUDIO_HANDLER_NAME = "_handle_audio"
_DIRECT_CONVERSATION_FLAGS = (F.FLAG_DIRECT_START, F.FLAG_DIRECT_SEND, F.FLAG_CLOSE_LINK, F.FLAG_CLOSE_LINK_ALIAS)


@dataclass(frozen=True)
class CommandClearance:
    """What the gate needs to clear the caller for one parsed command."""

    path: list[str]
    node: CommandDef
    auth: CommandAuth | None
    parsed: ParsedArgs
    target_session_id: str | None
    target_computer: str | None
    direct_conversation: bool


type ClearanceGate = Callable[[CommandClearance], None]


def main(clear: ClearanceGate) -> None:
    """Route one telec invocation; ``clear`` admits the caller for a real command."""
    # Handle shell completion before any other setup
    if os.environ.get("TELEC_COMPLETE"):  # fmt: skip  # guard: direct-env-read - allowed: bootstrap or internal process signal
        _handle_completion()
        return

    argv = sys.argv[1:]

    # Handle root help before command resolution or clearance.
    if argv and _maybe_show_help(None, argv):
        return

    if argv:
        _handle_cli_argv(argv, clear)
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


def _effective_auth(node: CommandDef, parsed: ParsedArgs) -> CommandAuth | None:
    """Return the node's declaration, conditioned on which of its flag-conditioned flags are present."""
    auth = node.auth
    if auth is None or not auth.when_flag:
        return auth
    declared = {candidate.long: candidate for candidate in node.flags}
    present = frozenset(
        condition.flag
        for condition in auth.when_flag
        if condition.flag in declared and parsed.has(declared[condition.flag])
    )
    return auth.conditioned(present)


def _handle_cli_command(argv: list[str], clear: ClearanceGate) -> None:
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
    parsed = parse_command_args(node, remainder)
    target_computer = parsed.value(F.FLAG_COMPUTER) if F.FLAG_COMPUTER in node.flags else None
    targets = parsed.values(F.FLAG_COMPUTER_MANY) if F.FLAG_COMPUTER_MANY in node.flags else ()
    direct_conversation = any(flag in node.flags and parsed.has(flag) for flag in _DIRECT_CONVERSATION_FLAGS)
    auth = _effective_auth(node, parsed)
    if auth is None or not admits_any_caller(auth.caller_independent, node.desk):
        for target in targets or (target_computer,):
            clear(
                CommandClearance(
                    path=path,
                    node=node,
                    auth=auth,
                    parsed=parsed,
                    target_session_id=target_session_id,
                    target_computer=target,
                    direct_conversation=direct_conversation,
                )
            )

    if node.addressed_at_boundary:
        from teleclaude.cli.telec.addressing import address_computer  # noqa: PLC0415 - real commands only.

        address_computer(target_computer)
        args = without_value_flag(args, F.FLAG_COMPUTER)
    handler = _resolve_cli_handler(cmd_enum, args)
    if handler is None:
        print(f"Unknown command: /{cmd}")
        print(_usage())
        return
    _dispatch_handler(handler)


def _handle_cli_argv(argv: list[str], clear: ClearanceGate) -> None:
    token = argv[0].lstrip("/")
    if token in {cmd.value for cmd in TelecCommand} or argv[0].startswith("/"):
        _handle_cli_command(argv, clear)
        return
    print(f"Unknown command: {argv[0]}")
    print(_usage())
    raise SystemExit(1)


def _start_tui() -> None:
    importlib.import_module(_LOGGING_MODULE).setup_logging()
    tui = importlib.import_module("teleclaude.cli.telec._run_tui")
    tui.start_tui()


def _session_action_target(node: CommandDef, args: list[str]) -> str | None:
    if node.auth is None or node.auth.scope is not CommandScope.TARGET_SESSION:
        return None
    parsed = parse_command_args(node, args)
    if parsed.positionals:
        return parsed.positionals[0]
    return parsed.value(F.FLAG_SESSION) if F.FLAG_SESSION in node.flags else None


def _dispatch_handler(handler: Callable[[], None]) -> None:
    importlib.import_module("teleclaude.logging_config").setup_logging()
    try:
        handler()
    except Exception as exc:
        if _is_loaded_exception(exc, "teleclaude.cli.tool_client", "ToolAPIError"):
            cast(_ToolAPIError, exc).exit_if_not_accepted()
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
        TelecCommand.AGENTS: _lazy("teleclaude.cli.tool_commands.infra", "handle_agents"),
        TelecCommand.OPERATIONS: _lazy("teleclaude.cli.tool_commands.todo", "handle_operations"),
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
        TelecCommand.REPO: _lazy("teleclaude.cli.telec.handlers.code", "handle_code"),
        TelecCommand.MESSAGE: _lazy("teleclaude.cli.telec.handlers.message", "_handle_message"),
        TelecCommand.AUDIO: _lazy(_AUDIO_HANDLER_MODULE, _AUDIO_HANDLER_NAME),
        TelecCommand.SYNC: _lazy("teleclaude.cli.telec.handlers.sync", "handle_sync"),
        TelecCommand.APP: _lazy("teleclaude.cli.telec.handlers.app", "handle_app"),
    }
    if cmd_enum is None:
        return None
    return handlers.get(cmd_enum)
