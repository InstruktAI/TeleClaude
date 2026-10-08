"""telec: TUI client for TeleClaude."""

import importlib
import os
import sys
from collections.abc import Callable
from pathlib import Path

from teleclaude.caller_identity import Company, Person, Platform, Project, ProjectPath, RelayedAct, RoleTarget
from teleclaude.cli import CommandScope, ConfigSubjectType
from teleclaude.cli.session_auth import (
    ComputerTargetDisposition,
    classify_computer_target,
    require_cli_clearance,
)
from teleclaude.cli.telec.handlers._arg_parsing import CliUsageError, ParsedArgs, parse_command_args
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
from teleclaude.constants import MAIN_MODULE
from teleclaude.paths import invocation_cwd
from teleclaude.slug import normalize_slug

from . import flags as F

_INVALID_CONFIGURATION_ERROR = "Error: invalid configuration.\n%s"
_RELAYED_ACT_PATHS = frozenset(act.value.removeprefix("telec ") for act in RelayedAct)
_DIRECT_CONVERSATION_FLAGS = (F.FLAG_DIRECT_SEND, F.FLAG_CLOSE_LINK, F.FLAG_CLOSE_LINK_ALIAS)

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


def _role_target_for_command(
    path: list[str],
    node: CommandDef,
    auth: CommandAuth | None,
    parsed: ParsedArgs,
    target_computer: str | None,
    direct_conversation: bool,
) -> RoleTarget | None:
    """Resolve the declared person-role object from the parsed command target."""
    if auth is None or auth.caller_independent:
        return None
    if classify_computer_target(target_computer) is ComputerTargetDisposition.REMOTE:
        if " ".join(path) in _RELAYED_ACT_PATHS:
            return Platform() if direct_conversation else None
        return Platform()
    if auth.scope is CommandScope.PLATFORM:
        return Platform()
    if auth.scope is CommandScope.CONFIG_SUBJECT:
        if len(path) < 2 or not parsed.positionals:
            return Platform()
        try:
            subject_type = ConfigSubjectType(path[1])
        except ValueError:
            return Platform()
        subject = parsed.positionals[0]
        if subject_type is ConfigSubjectType.PERSON:
            return Person(subject)
        if subject_type is ConfigSubjectType.COMPANY:
            return Company(subject)
        return Project(subject)
    if auth.scope in (CommandScope.TARGET_SESSION, CommandScope.CALLER_PERSON):
        return None
    if auth.scope is CommandScope.NAMED_COMPANY:
        return _named_company_target(node, auth, parsed)
    if auth.scope is CommandScope.NAMED_TRUSTED_DIRECTORY:
        if auth.scope_flag is None:
            return Platform()
        flag = next((candidate for candidate in node.flags if candidate.long == auth.scope_flag), None)
        if flag is None:
            return Platform()
        if parsed.value(flag) is None:
            return ProjectPath(invocation_cwd())
        return None
    if auth.scope is CommandScope.TARGET_PATH:
        target_value: str | None = None
        if auth.scope_flag is not None:
            flag = next((candidate for candidate in node.flags if candidate.long == auth.scope_flag), None)
            if flag is not None:
                target_value = parsed.value(flag)
        if target_value is None:
            return ProjectPath(invocation_cwd())
        return ProjectPath(Path(target_value).expanduser())
    return ProjectPath(invocation_cwd())


def _named_company_target(node: CommandDef, auth: CommandAuth, parsed: ParsedArgs) -> RoleTarget:
    """Resolve the company a command names: its scope flag's value, else its normalized first positional."""
    flag = next((candidate for candidate in node.flags if candidate.long == auth.scope_flag), None)
    named = parsed.value(flag) if flag is not None else None
    if named is None and parsed.positionals:
        named = normalize_slug(parsed.positionals[0])
    return Company(named.strip()) if named and named.strip() else Platform()


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
    parsed = parse_command_args(node, remainder)
    target_computer = parsed.value(F.FLAG_COMPUTER) if F.FLAG_COMPUTER in node.flags else None
    direct_conversation = any(flag in node.flags and parsed.has(flag) for flag in _DIRECT_CONVERSATION_FLAGS)
    auth = _effective_auth(node, parsed)
    role_target = _role_target_for_command(path, node, auth, parsed, target_computer, direct_conversation)
    require_cli_clearance(
        command_path,
        target_session_id,
        auth,
        role_target=role_target,
        target_computer=target_computer,
        direct_conversation=direct_conversation,
        desk_command=node.desk,
    )

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
        TelecCommand.SYNC: _lazy("teleclaude.cli.telec.handlers.sync", "handle_sync"),
    }
    if cmd_enum is None:
        return None
    return handlers.get(cmd_enum)


if __name__ == MAIN_MODULE:
    main()
