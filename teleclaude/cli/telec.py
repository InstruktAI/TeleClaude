"""telec: TUI client for TeleClaude."""

import asyncio
import curses
import os
import subprocess
import sys
from enum import Enum
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.cli.api_client import APIError, TelecAPIClient
from teleclaude.cli.models import CreateSessionResult
from teleclaude.config import config
from teleclaude.constants import ENV_ENABLE, MAIN_MODULE
from teleclaude.logging_config import setup_logging
from teleclaude.project_setup import init_project
from teleclaude.todo_scaffold import create_todo_skeleton

TMUX_ENV_KEY = "TMUX"
TUI_ENV_KEY = "TELEC_TUI_SESSION"
TUI_SESSION_NAME = "tc_tui"


class TelecCommand(str, Enum):
    """Supported telec CLI commands."""

    LIST = "list"
    CLAUDE = "claude"
    GEMINI = "gemini"
    CODEX = "codex"
    REVIVE = "revive"
    INIT = "init"
    SYNC = "sync"
    WATCH = "watch"
    DOCS = "docs"
    TODO = "todo"


# Completion definitions: (short, long, description)
_COMMANDS = [cmd.value for cmd in TelecCommand]
_COMMAND_DESCRIPTIONS = {
    "list": "List active TeleClaude sessions across all computers",
    "claude": "Start interactive Claude Code session (fast/med/slow)",
    "gemini": "Start interactive Gemini session (fast/med/slow)",
    "codex": "Start interactive Codex session (fast/med/slow)",
    "revive": "Revive session by TeleClaude session ID",
    "init": "Set up project hooks, watchers, and doc sync",
    "sync": "Validate refs and build doc artifacts",
    "watch": "Auto-sync docs on file changes",
    "docs": "Query doc snippets (index or fetch by ID)",
    "todo": "Scaffold a todo folder and core files",
}
_DOCS_FLAGS = [
    ("-h", "--help", "Show usage information"),
    ("-b", "--baseline-only", "Show only baseline snippets"),
    ("-t", "--third-party", "Include third-party docs"),
    ("-a", "--areas", "Filter by taxonomy type"),
    ("-d", "--domains", "Filter by domain"),
    ("-p", "--project-root", "Project root directory"),
]
_SYNC_FLAGS = [
    ("-h", "--help", "Show usage information"),
    (None, "--warn-only", "Warn but don't fail"),
    (None, "--validate-only", "Validate without building"),
    (None, "--project-root", "Project root directory"),
]
_WATCH_FLAGS = [
    ("-h", "--help", "Show usage information"),
    (None, "--project-root", "Project root directory"),
]
_REVIVE_FLAGS = [
    ("-h", "--help", "Show usage information"),
    (None, "--attach", "Attach to tmux session after revive"),
]
_AGENT_MODES = [
    ("fast", "Cheapest, quickest"),
    ("med", "Balanced"),
    ("slow", "Most capable"),
]
_TAXONOMY_TYPES = [
    ("principle", "Core principles"),
    ("concept", "Key concepts"),
    ("policy", "Rules and policies"),
    ("procedure", "Step-by-step guides"),
    ("design", "Architecture docs"),
    ("spec", "Specifications"),
]
_DOMAINS = [
    ("software-development", "Software dev domain"),
    ("general", "Cross-domain"),
]
_TODO_SUBCOMMANDS = [
    ("create", "Create todo skeleton files for a slug"),
    ("validate", "Validate todo files and state.json schema"),
]
_TODO_FLAGS = [
    (None, "--project-root", "Project root directory"),
    (None, "--after", "Comma-separated dependency slugs"),
]


def _print_completion(value: str, description: str) -> None:
    """Print completion in value<TAB>description format for zsh."""
    print(f"{value}\t{description}")


def _handle_completion() -> None:
    """Handle shell completion requests."""
    comp_line = os.environ.get("COMP_LINE", "")
    parts = comp_line.split()

    # Remove "telec" from parts if present
    if parts and parts[0] == "telec":
        parts = parts[1:]

    # No command yet - complete commands
    if not parts:
        for cmd in _COMMANDS:
            _print_completion(cmd, _COMMAND_DESCRIPTIONS.get(cmd, ""))
        return

    cmd = parts[0]
    rest = parts[1:]
    current = parts[-1] if parts else ""
    is_partial = not comp_line.endswith(" ")

    # Completing the command itself
    if len(parts) == 1 and is_partial:
        for c in _COMMANDS:
            if c.startswith(current):
                _print_completion(c, _COMMAND_DESCRIPTIONS.get(c, ""))
        return

    # Command-specific completions
    if cmd == "docs":
        _complete_docs(rest, current, is_partial)
    elif cmd == "sync":
        _complete_flags(_SYNC_FLAGS, rest, current, is_partial)
    elif cmd == "watch":
        _complete_flags(_WATCH_FLAGS, rest, current, is_partial)
    elif cmd == "revive":
        _complete_flags(_REVIVE_FLAGS, rest, current, is_partial)
    elif cmd in ("claude", "gemini", "codex"):
        _complete_agent(rest, current, is_partial)
    elif cmd == "todo":
        _complete_todo(rest, current, is_partial)
    # list, init have no further completions


def _flag_used(flag_tuple: tuple[str | None, str, str], used: set[str]) -> bool:
    """Check if a flag (short or long form) was already used."""
    short, long, _ = flag_tuple
    return (short and short in used) or (long in used)


def _flag_matches(flag_tuple: tuple[str | None, str, str], prefix: str) -> bool:
    """Check if a flag matches the current prefix."""
    short, long, _ = flag_tuple
    return (short and short.startswith(prefix)) or long.startswith(prefix)


def _print_flag(flag_tuple: tuple[str | None, str, str]) -> None:
    """Print a flag completion with optional short form."""
    short, long, desc = flag_tuple
    if short:
        _print_completion(f"{short}, {long}", desc)
    else:
        _print_completion(long, desc)


def _complete_docs(rest: list[str], current: str, is_partial: bool) -> None:
    """Complete telec docs arguments."""
    used_flags = set(rest)

    # If completing a flag
    if is_partial and current.startswith("-"):
        for flag in _DOCS_FLAGS:
            if _flag_matches(flag, current) and not _flag_used(flag, used_flags):
                _print_flag(flag)
        return

    # After --areas, suggest taxonomy types
    if rest and rest[-1] in ("--areas", "-a"):
        for value, desc in _TAXONOMY_TYPES:
            _print_completion(value, desc)
        return

    # After --domains, suggest common domains
    if rest and rest[-1] in ("--domains", "-d"):
        for value, desc in _DOMAINS:
            _print_completion(value, desc)
        return

    # Default: suggest unused flags
    for flag in _DOCS_FLAGS:
        if not _flag_used(flag, used_flags):
            _print_flag(flag)


def _complete_flags(flags: list[tuple[str | None, str, str]], rest: list[str], current: str, is_partial: bool) -> None:
    """Complete simple flag-only commands."""
    used_flags = set(rest)
    if is_partial and current.startswith("-"):
        for flag in flags:
            if _flag_matches(flag, current) and not _flag_used(flag, used_flags):
                _print_flag(flag)
    else:
        for flag in flags:
            if not _flag_used(flag, used_flags):
                _print_flag(flag)


def _complete_agent(rest: list[str], current: str, is_partial: bool) -> None:
    """Complete agent commands (claude/gemini/codex)."""
    # First arg is mode
    if not rest:
        for mode_value, mode_desc in _AGENT_MODES:
            if not is_partial or mode_value.startswith(current):
                _print_completion(mode_value, mode_desc)
    elif len(rest) == 1 and is_partial:
        for mode_value, mode_desc in _AGENT_MODES:
            if mode_value.startswith(current):
                _print_completion(mode_value, mode_desc)


def _complete_todo(rest: list[str], current: str, is_partial: bool) -> None:
    """Complete telec todo arguments."""
    if not rest:
        for subcommand, desc in _TODO_SUBCOMMANDS:
            if not is_partial or subcommand.startswith(current):
                _print_completion(subcommand, desc)
        return

    subcommand = rest[0]
    if subcommand != "create":
        return

    used = set(rest[1:])
    if is_partial and current.startswith("-"):
        for flag in _TODO_FLAGS:
            if _flag_matches(flag, current) and not _flag_used(flag, used):
                _print_flag(flag)
        return

    for flag in _TODO_FLAGS:
        if not _flag_used(flag, used):
            _print_flag(flag)


def main() -> None:
    """Main entry point for telec CLI."""
    # Handle shell completion before any other setup
    if os.environ.get("TELEC_COMPLETE"):
        _handle_completion()
        return

    setup_logging()
    logger = get_logger(__name__)
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

    # TUI mode - ensure we're in tmux for pane preview
    if not os.environ.get(TMUX_ENV_KEY):
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
        for key, value in os.environ.items():
            if key == TUI_ENV_KEY:
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


def _run_tui() -> None:
    """Run TUI application."""
    logger = get_logger(__name__)
    # Lazy import: TelecApp applies nest_asyncio which breaks httpx for CLI commands
    from teleclaude.cli.tui.app import TelecApp

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    api = TelecAPIClient()
    app = TelecApp(api)

    try:
        _ensure_tmux_status_hidden_for_tui()
        _ensure_tmux_mouse_on()
        loop.run_until_complete(app.initialize())
        curses.wrapper(app.run)
    except KeyboardInterrupt:
        pass  # Clean exit on Ctrl-C
    except Exception:
        logger.exception("telec TUI crashed")
    finally:
        loop.run_until_complete(api.close())
        loop.close()
        _maybe_kill_tui_session()


def _handle_cli_command(argv: list[str]) -> None:
    """Handle CLI shortcuts like /list, /claude, etc.

    Args:
        argv: Command-line arguments
    """
    cmd = argv[0].lstrip("/")
    args = argv[1:]

    try:
        cmd_enum = TelecCommand(cmd)
    except ValueError:
        cmd_enum = None

    if cmd_enum is TelecCommand.LIST:
        api = TelecAPIClient()
        asyncio.run(_list_sessions(api))
    elif cmd_enum in (TelecCommand.CLAUDE, TelecCommand.GEMINI, TelecCommand.CODEX):
        mode = args[0] if args else "slow"
        prompt = " ".join(args[1:]) if len(args) > 1 else None
        _quick_start(cmd_enum.value, mode, prompt)
    elif cmd_enum is TelecCommand.REVIVE:
        _handle_revive(args)
    elif cmd_enum is TelecCommand.INIT:
        init_project(Path.cwd())
    elif cmd_enum is TelecCommand.SYNC:
        _handle_sync(args)
    elif cmd_enum is TelecCommand.WATCH:
        _handle_watch(args)
    elif cmd_enum is TelecCommand.DOCS:
        _handle_docs(args)
    elif cmd_enum is TelecCommand.TODO:
        _handle_todo(args)
    else:
        print(f"Unknown command: /{cmd}")
        print(_usage())


def _maybe_kill_tui_session() -> None:
    """Kill the tc_tui tmux session if telec created it."""
    if os.environ.get(TUI_ENV_KEY) != ENV_ENABLE:
        return
    if not os.environ.get(TMUX_ENV_KEY):
        return

    tmux = config.computer.tmux_binary
    try:
        result = subprocess.run(
            [tmux, "display-message", "-p", "#S"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout.strip() != TUI_SESSION_NAME:
            return
        subprocess.run(
            [tmux, "kill-session", "-t", TUI_SESSION_NAME],
            check=False,
            capture_output=True,
        )
    except OSError:
        return


def _ensure_tmux_mouse_on() -> None:
    """Ensure tmux mouse is enabled for the current window."""
    if not os.environ.get(TMUX_ENV_KEY):
        return
    tmux = config.computer.tmux_binary
    try:
        subprocess.run(
            [tmux, "set-option", "-w", "mouse", "on"],
            check=False,
            capture_output=True,
        )
    except OSError:
        return


def _ensure_tmux_status_hidden_for_tui() -> None:
    """Hide tmux status bar for the dedicated tc_tui session."""
    if not os.environ.get(TMUX_ENV_KEY):
        return
    tmux = config.computer.tmux_binary
    try:
        current = subprocess.run(
            [tmux, "display-message", "-p", "#S"],
            capture_output=True,
            text=True,
            check=False,
        )
        if current.stdout.strip() != TUI_SESSION_NAME:
            return
        subprocess.run(
            [tmux, "set-option", "-t", TUI_SESSION_NAME, "status", "off"],
            check=False,
            capture_output=True,
        )
    except OSError:
        return


async def _list_sessions(api: TelecAPIClient) -> None:
    """List sessions to stdout.

    Args:
        api: API client
    """
    await api.connect()
    try:
        sessions = await api.list_sessions()
        for session in sessions:
            computer = session.computer or "?"
            agent = session.active_agent or "?"
            mode = session.thinking_mode or "?"
            title = session.title
            print(f"{computer}: {agent}/{mode} - {title}")
    finally:
        await api.close()


def _quick_start(agent: str, mode: str, prompt: str | None) -> None:
    """Quick start a session via the daemon (ensures proper tmux env).

    Args:
        agent: Agent name (claude, gemini, codex)
        mode: Thinking mode (fast, med, slow)
        prompt: Initial prompt (optional - if None, starts interactive session)
    """
    try:
        result = asyncio.run(_quick_start_via_api(agent, mode, prompt))
    except APIError as e:
        print(f"Error: {e}")
        return

    tmux_session_name = result.tmux_session_name or ""
    if not tmux_session_name:
        session_id = result.session_id
        if session_id:
            print(f"Session {session_id[:8]} created, but no tmux session name returned.")
        else:
            print("Session created, but no tmux session name returned.")
        return

    _attach_tmux_session(tmux_session_name)


def _handle_revive(args: list[str]) -> None:
    """Handle telec revive command."""
    if not args or args[0] in ("--help", "-h"):
        print(_revive_usage())
        return

    attach = False
    session_id: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--attach":
            attach = True
            i += 1
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_revive_usage())
            raise SystemExit(1)
        else:
            if session_id is not None:
                print("Only one session_id is allowed.")
                print(_revive_usage())
                raise SystemExit(1)
            session_id = arg
            i += 1

    if not session_id:
        print("Missing required session_id.")
        print(_revive_usage())
        raise SystemExit(1)

    _revive_session(session_id, attach)


def _revive_session(session_id: str, attach: bool) -> None:
    """Revive a session by TeleClaude session ID."""
    try:
        result = asyncio.run(_revive_session_via_api(session_id))
    except APIError as e:
        print(f"Error: {e}")
        return

    if result.status != "success":
        print(result.error or "Revive failed")
        return

    print(f"Revived session {result.session_id[:8]}")
    try:
        asyncio.run(_send_revive_enter_via_api(result.session_id))
    except APIError as e:
        print(f"Warning: revive kick failed: {e}")
    if attach and result.tmux_session_name:
        _attach_tmux_session(result.tmux_session_name)


async def _revive_session_via_api(session_id: str) -> CreateSessionResult:
    """Revive a session via API and return the response."""
    api = TelecAPIClient()
    await api.connect()
    try:
        return await api.revive_session(session_id)
    finally:
        await api.close()


async def _send_revive_enter_via_api(session_id: str) -> bool:
    """Send an enter key after revive so headless activity resumes immediately."""
    api = TelecAPIClient()
    await api.connect()
    try:
        return await api.send_keys(
            session_id=session_id,
            computer=config.computer.name,
            key="enter",
            count=1,
        )
    finally:
        await api.close()


async def _quick_start_via_api(agent: str, mode: str, prompt: str | None) -> CreateSessionResult:
    """Create a session via API and return the response."""
    api = TelecAPIClient()
    await api.connect()
    try:
        return await api.create_session(
            computer=config.computer.name,
            project_path=os.getcwd(),
            agent=agent,
            thinking_mode=mode,
            message=prompt,
        )
    finally:
        await api.close()


def _attach_tmux_session(tmux_session_name: str) -> None:
    """Attach or switch to a tmux session."""
    tmux = config.computer.tmux_binary
    if os.environ.get("TMUX"):
        subprocess.run([tmux, "switch-client", "-t", tmux_session_name], check=False)
        return

    os.execlp(tmux, tmux, "attach-session", "-t", tmux_session_name)


def _handle_sync(args: list[str]) -> None:
    """Handle telec sync command."""
    from teleclaude.sync import sync

    project_root = Path.cwd()
    warn_only = False
    validate_only = False

    i = 0
    while i < len(args):
        if args[i] == "--project-root" and i + 1 < len(args):
            project_root = Path(args[i + 1]).expanduser().resolve()
            i += 2
        elif args[i] == "--warn-only":
            warn_only = True
            i += 1
        elif args[i] == "--validate-only":
            validate_only = True
            i += 1
        else:
            i += 1

    ok = sync(project_root, validate_only=validate_only, warn_only=warn_only)
    if not ok:
        raise SystemExit(1)


def _handle_watch(args: list[str]) -> None:
    """Handle telec watch command."""
    from teleclaude.cli.watch import run_watch

    project_root = Path.cwd()
    i = 0
    while i < len(args):
        if args[i] == "--project-root" and i + 1 < len(args):
            project_root = Path(args[i + 1]).expanduser().resolve()
            i += 2
        else:
            i += 1

    run_watch(project_root)


def _handle_docs(args: list[str]) -> None:
    """Handle telec docs command.

    Phase 1 (index): telec docs [--baseline-only] [--third-party] [--areas TYPES] [--domains DOMAINS]
    Phase 2 (content): telec docs id1 id2 id3 (positional args = snippet IDs)
    """
    # Handle --help early
    if args and args[0] in ("--help", "-h"):
        print(_docs_usage())
        return

    from teleclaude.context_selector import build_context_output

    project_root = Path.cwd()
    baseline_only = False
    third_party = False
    areas: list[str] = []
    domains: list[str] | None = None
    snippet_ids: list[str] = []

    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--help", "-h"):
            print(_docs_usage())
            return
        if arg in ("--project-root", "-p") and i + 1 < len(args):
            project_root = Path(args[i + 1]).expanduser().resolve()
            i += 2
        elif arg in ("--baseline-only", "-b"):
            baseline_only = True
            i += 1
        elif arg in ("--third-party", "-t"):
            third_party = True
            i += 1
        elif arg in ("--areas", "-a") and i + 1 < len(args):
            areas = [a.strip() for a in args[i + 1].split(",") if a.strip()]
            i += 2
        elif arg in ("--domains", "-d") and i + 1 < len(args):
            domains = [d.strip() for d in args[i + 1].split(",") if d.strip()]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_docs_usage())
            raise SystemExit(1)
        else:
            # Positional argument = snippet ID (may be comma-separated)
            for part in arg.split(","):
                part = part.strip()
                if part:
                    snippet_ids.append(part)
            i += 1

    # If snippet_ids provided, it's phase 2 - ignore filter flags
    output = build_context_output(
        areas=areas if not snippet_ids else [],
        project_root=project_root,
        snippet_ids=snippet_ids if snippet_ids else None,
        baseline_only=baseline_only if not snippet_ids else False,
        include_third_party=third_party if not snippet_ids else False,
        domains=domains if not snippet_ids else None,
    )
    print(output)


def _docs_usage() -> str:
    """Return usage string for telec docs."""
    return (
        "Usage:\n"
        "  telec docs                                  # Phase 1: Show snippet index\n"
        "  telec docs --baseline-only                  # Phase 1: Show only baseline snippets\n"
        "  telec docs --third-party                    # Phase 1: Include third-party docs\n"
        "  telec docs --areas policy,procedure         # Phase 1: Filter by taxonomy type\n"
        "  telec docs --domains software-development   # Phase 1: Filter by domain\n"
        "  telec docs --project-root /path/to/project  # Query different project\n"
        "  telec docs id1 id2 id3                      # Phase 2: Get content for IDs\n"
        "  telec docs id1,id2,id3                      # Phase 2: Comma-separated IDs\n"
        "\n"
        "Options:\n"
        "  -b, --baseline-only   Show only baseline snippets (auto-loaded at session start)\n"
        "  -t, --third-party     Include third-party documentation\n"
        "  -a, --areas           Comma-separated taxonomy types (principle,concept,policy,etc.)\n"
        "  -d, --domains         Comma-separated domains (software-development,general,etc.)\n"
        "  -p, --project-root    Project root directory (defaults to cwd)\n"
    )


def _usage() -> str:
    """Return usage string.

    Returns:
        Usage text
    """
    return (
        "Usage:\n"
        "  telec                          # Open TUI (Sessions view)\n"
        "  telec list                     # List sessions (stdout, no TUI)\n"
        "  telec claude [mode] [prompt]   # Start Claude (mode: fast/med/slow, prompt optional)\n"
        "  telec gemini [mode] [prompt]   # Start Gemini (mode: fast/med/slow, prompt optional)\n"
        "  telec codex [mode] [prompt]    # Start Codex (mode: fast/med/slow/deep, prompt optional)\n"
        "  telec revive <session_id> [--attach]\n"
        "                                 # Revive session by TeleClaude session ID\n"
        "  telec init                     # Initialize docs sync and auto-rebuild watcher\n"
        "  telec sync [--warn-only] [--validate-only] [--project-root PATH]\n"
        "                                 # Validate, build indexes, and deploy artifacts\n"
        "  telec watch [--project-root PATH]\n"
        "                                 # Watch project for changes and auto-sync\n"
        "  telec docs [OPTIONS] [IDS...]  # Query documentation snippets (use --help for details)\n"
        "  telec todo create <slug> [--project-root PATH] [--after dep1,dep2]\n"
        "                                 # Scaffold todo files without modifying roadmap\n"
        "  telec todo validate [slug] [--project-root PATH]\n"
        "                                 # Validate todo files and state.json schema\n"
    )


def _revive_usage() -> str:
    """Return usage string for telec revive."""
    return (
        "Usage:\n"
        "  telec revive <session_id> [--attach]\n"
        "\n"
        "Options:\n"
        "  --attach      Attach to tmux session after revive\n"
    )


def _handle_todo(args: list[str]) -> None:
    """Handle telec todo commands."""
    if not args or args[0] in ("--help", "-h"):
        print(_todo_usage())
        return

    subcommand = args[0]
    if subcommand == "create":
        _handle_todo_create(args[1:])
    elif subcommand == "validate":
        _handle_todo_validate(args[1:])
    else:
        print(f"Unknown todo subcommand: {subcommand}")
        print(_todo_usage())
        raise SystemExit(1)


def _handle_todo_validate(args: list[str]) -> None:
    """Handle telec todo validate."""
    if args and args[0] in ("--help", "-h"):
        print(_todo_usage())
        return

    from teleclaude.resource_validation import validate_all_todos, validate_todo

    slug: str | None = None
    project_root = Path.cwd()

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--project-root" and i + 1 < len(args):
            project_root = Path(args[i + 1]).expanduser().resolve()
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_todo_usage())
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed for validation.")
                print(_todo_usage())
                raise SystemExit(1)
            slug = arg
            i += 1

    errors = []
    if slug:
        errors = validate_todo(slug, project_root)
    else:
        errors = validate_all_todos(project_root)

    if errors:
        print("Todo validation failed:")
        for error in errors:
            print(f"  - {error}")
        raise SystemExit(1)

    if slug:
        print(f"✓ Todo {slug} is valid")
    else:
        print("✓ All active todos are valid")


def _handle_todo_create(args: list[str]) -> None:
    """Handle telec todo create."""
    if not args or args[0] in ("--help", "-h"):
        print(_todo_usage())
        return

    slug: str | None = None
    project_root = Path.cwd()
    after: list[str] | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--project-root" and i + 1 < len(args):
            project_root = Path(args[i + 1]).expanduser().resolve()
            i += 2
        elif arg == "--after" and i + 1 < len(args):
            after = [part.strip() for part in args[i + 1].split(",") if part.strip()]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_todo_usage())
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                print(_todo_usage())
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_todo_usage())
        raise SystemExit(1)

    try:
        todo_dir = create_todo_skeleton(project_root, slug, after=after)
    except (ValueError, FileExistsError) as exc:
        print(f"Error: {exc}")
        raise SystemExit(1) from exc

    print(f"Created todo skeleton: {todo_dir}")
    if after:
        print(f"Updated dependencies for {slug}: {', '.join(after)}")


def _todo_usage() -> str:
    """Return usage string for telec todo."""
    return (
        "Usage:\n"
        "  telec todo create <slug> [--project-root PATH] [--after dep1,dep2]\n"
        "  telec todo validate [slug] [--project-root PATH]\n"
        "\n"
        "Notes:\n"
        "  - create: Scaffolds todos/{slug}/requirements.md, implementation-plan.md, etc.\n"
        "  - validate: Checks state.json schema and required files for 'Ready' status.\n"
        "  - If slug is omitted for validate, all active todos are checked.\n"
        "  - Does NOT modify todos/roadmap.md\n"
    )


if __name__ == MAIN_MODULE:
    main()
