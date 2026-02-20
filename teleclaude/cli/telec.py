"""telec: TUI client for TeleClaude."""

import asyncio
import os
import subprocess
import sys
import time as _t
from enum import Enum
from pathlib import Path

_BOOT = _t.monotonic()

from instrukt_ai_logging import get_logger  # noqa: E402

from teleclaude.cli.api_client import APIError, TelecAPIClient  # noqa: E402
from teleclaude.cli.models import CreateSessionResult  # noqa: E402
from teleclaude.config import config  # noqa: E402
from teleclaude.constants import ENV_ENABLE, MAIN_MODULE  # noqa: E402
from teleclaude.logging_config import setup_logging  # noqa: E402
from teleclaude.project_setup import init_project  # noqa: E402
from teleclaude.todo_scaffold import create_todo_skeleton  # noqa: E402

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
    ROADMAP = "roadmap"
    CONFIG = "config"
    ONBOARD = "onboard"


# Completion definitions: (short, long, description)
_COMMANDS = [cmd.value for cmd in TelecCommand]
_COMMAND_DESCRIPTIONS = {
    "list": "List sessions (default: spawned by current session, --all for all)",
    "claude": "Start interactive Claude Code session (fast/med/slow)",
    "gemini": "Start interactive Gemini session (fast/med/slow)",
    "codex": "Start interactive Codex session (fast/med/slow)",
    "revive": "Revive session by TeleClaude session ID",
    "init": "Set up project hooks, watchers, and doc sync",
    "sync": "Validate refs and build doc artifacts",
    "watch": "Auto-sync docs on file changes",
    "docs": "Query doc snippets (index or fetch by ID)",
    "todo": "Scaffold a todo folder and core files",
    "roadmap": "View and manage the work item roadmap",
    "config": "Interactive configuration (or get/patch/validate subcommands)",
    "onboard": "Guided onboarding wizard for first-run setup",
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
_LIST_FLAGS = [
    ("-h", "--help", "Show usage information"),
    (None, "--all", "Show all sessions (default: only spawned sessions)"),
]
_CONFIG_SUBCOMMANDS = [
    ("get", "Get config values (telec config get [paths...])"),
    ("patch", "Patch config values (telec config patch --yaml '...')"),
    ("validate", "Full validation"),
    ("people", "Manage people (list/add/edit/remove)"),
    ("env", "Manage environment variables (list/set)"),
    ("notify", "Toggle notification settings"),
    ("invite", "Generate invite links for a person"),
]
_CONFIG_FLAGS = [
    ("-h", "--help", "Show usage information"),
    ("-p", "--project-root", "Project root directory"),
    ("-f", "--format", "Output format (yaml or json)"),
]
_TODO_SUBCOMMANDS = [
    ("create", "Create todo skeleton files for a slug"),
    ("validate", "Validate todo files and state.json schema"),
]
_TODO_FLAGS = [
    (None, "--project-root", "Project root directory"),
    (None, "--after", "Comma-separated dependency slugs"),
]
_ROADMAP_SUBCOMMANDS = [
    ("add", "Add entry to the roadmap"),
    ("remove", "Remove entry from the roadmap"),
    ("move", "Reorder an entry in the roadmap"),
    ("deps", "Set dependencies for an entry"),
]
_ROADMAP_FLAGS = [
    (None, "--group", "Visual grouping label"),
    (None, "--after", "Comma-separated dependency slugs (add/deps) or slug to insert after (move)"),
    (None, "--before", "Slug to insert before (move/add)"),
    (None, "--description", "Summary description"),
    (None, "--project-root", "Project root directory"),
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
    elif cmd == "roadmap":
        _complete_roadmap(rest, current, is_partial)
    elif cmd == "config":
        _complete_config(rest, current, is_partial)
    elif cmd == "list":
        _complete_flags(_LIST_FLAGS, rest, current, is_partial)
    # init, onboard have no further completions


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


def _complete_roadmap(rest: list[str], current: str, is_partial: bool) -> None:
    """Complete telec roadmap arguments."""
    if not rest:
        for subcommand, desc in _ROADMAP_SUBCOMMANDS:
            if not is_partial or subcommand.startswith(current):
                _print_completion(subcommand, desc)
        return

    used = set(rest[1:])
    if is_partial and current.startswith("-"):
        for flag in _ROADMAP_FLAGS:
            if _flag_matches(flag, current) and not _flag_used(flag, used):
                _print_flag(flag)
        return

    for flag in _ROADMAP_FLAGS:
        if not _flag_used(flag, used):
            _print_flag(flag)


def _complete_config(rest: list[str], current: str, is_partial: bool) -> None:
    """Complete telec config arguments."""
    if not rest:
        for subcommand, desc in _CONFIG_SUBCOMMANDS:
            if not is_partial or subcommand.startswith(current):
                _print_completion(subcommand, desc)
        return

    used = set(rest)
    if is_partial and current.startswith("-"):
        for flag in _CONFIG_FLAGS:
            if _flag_matches(flag, current) and not _flag_used(flag, used):
                _print_flag(flag)
        return

    for flag in _CONFIG_FLAGS:
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
    logger.info("[PERF] main() imports done dt=%.3f", _t.monotonic() - _BOOT)
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


def _run_tui(start_view: int = 1, config_guided: bool = False) -> None:
    """Run TUI application.

    On SIGUSR2 the app exits with RELOAD_EXIT. We skip tmux session
    cleanup and os.execvp to restart the process, reloading all Python
    modules from disk.
    """
    logger = get_logger(__name__)
    _t0 = _t.monotonic()
    from teleclaude.cli.tui.app import RELOAD_EXIT, TelecApp

    logger.info("[PERF] _run_tui import TelecApp dt=%.3f", _t.monotonic() - _t0)
    api = TelecAPIClient()
    app = TelecApp(api, start_view=start_view)
    logger.info("[PERF] _run_tui TelecApp created dt=%.3f", _t.monotonic() - _t0)

    reload_requested = False

    try:
        _ensure_tmux_status_hidden_for_tui()
        _ensure_tmux_mouse_on()
        logger.info("[PERF] _run_tui pre-app.run dt=%.3f", _t.monotonic() - _t0)
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
    _run_tui(start_view=3, config_guided=guided)


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
        if args and args[0] in ("--help", "-h"):
            print(
                "Usage:\n"
                "  telec list           # List child sessions of the current session\n"
                "  telec list --all     # List all active sessions\n"
            )
            return
        show_all = "--all" in args
        api = TelecAPIClient()
        asyncio.run(_list_sessions(api, show_all=show_all))
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
    elif cmd_enum is TelecCommand.ROADMAP:
        _handle_roadmap(args)
    elif cmd_enum is TelecCommand.CONFIG:
        _handle_config(args)
    elif cmd_enum is TelecCommand.ONBOARD:
        _handle_onboard(args)
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


def _get_caller_session_id() -> str | None:
    """Read the calling session's ID from $TMPDIR/teleclaude_session_id."""
    tmpdir = os.environ.get("TMPDIR", "")
    if not tmpdir:
        return None
    id_file = Path(tmpdir) / "teleclaude_session_id"
    try:
        return id_file.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


async def _list_sessions(api: TelecAPIClient, *, show_all: bool = False) -> None:
    """List sessions to stdout.

    Default: show only sessions spawned by the calling session (via initiator_session_id).
    With --all: show all sessions.

    Args:
        api: API client
        show_all: If True, list all sessions regardless of initiator
    """
    caller_id = None if show_all else _get_caller_session_id()

    await api.connect()
    try:
        sessions = await api.list_sessions()
        if caller_id:
            sessions = [s for s in sessions if s.initiator_session_id == caller_id]
        for session in sessions:
            computer = session.computer or "?"
            agent = session.active_agent or "?"
            mode = session.thinking_mode or "?"
            title = session.title
            print(f"{computer}: {agent}/{mode} - {title}")
        if not sessions and caller_id:
            print("No child sessions. Use --all to list all sessions.")
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
        "  telec list [--all]             # List sessions (default: spawned by current, --all for all)\n"
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
        "  telec roadmap                  # Show roadmap (grouped, with deps & state)\n"
        "  telec roadmap add <slug>       # Add entry (--group, --after, --description, --before)\n"
        "  telec roadmap remove <slug>    # Remove entry\n"
        "  telec roadmap move <slug>      # Reorder (--before or --after)\n"
        "  telec roadmap deps <slug>      # Set dependencies (--after dep1,dep2)\n"
        "  telec config                   # Interactive configuration menu\n"
        "  telec config get/patch/validate # Config subcommands (daemon config.yml)\n"
        "  telec onboard                  # Guided onboarding wizard\n"
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
        "  - Use --after with create to also register the entry in roadmap.yaml.\n"
    )


def _handle_roadmap(args: list[str]) -> None:
    """Handle telec roadmap commands."""
    if args and args[0] in ("--help", "-h"):
        print(_roadmap_usage())
        return

    if not args:
        _handle_roadmap_show(args)
        return

    subcommand = args[0]
    if subcommand == "add":
        _handle_roadmap_add(args[1:])
    elif subcommand == "remove":
        _handle_roadmap_remove(args[1:])
    elif subcommand == "move":
        _handle_roadmap_move(args[1:])
    elif subcommand == "deps":
        _handle_roadmap_deps(args[1:])
    elif subcommand.startswith("-"):
        # Flags passed to show (e.g. --project-root)
        _handle_roadmap_show(args)
    else:
        print(f"Unknown roadmap subcommand: {subcommand}")
        print(_roadmap_usage())
        raise SystemExit(1)


def _handle_roadmap_show(args: list[str]) -> None:
    """Display the roadmap grouped by group, with deps and state."""
    import json

    from teleclaude.core.next_machine.core import load_roadmap

    project_root = Path.cwd()
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--project-root" and i + 1 < len(args):
            project_root = Path(args[i + 1]).expanduser().resolve()
            i += 2
        else:
            i += 1

    entries = load_roadmap(str(project_root))
    if not entries:
        print("Roadmap is empty.")
        return

    # Group entries preserving order of first appearance
    from teleclaude.core.next_machine.core import RoadmapEntry

    groups: dict[str, list[RoadmapEntry]] = {}
    for entry in entries:
        key = entry.group or ""
        groups.setdefault(key, []).append(entry)

    todos_root = project_root / "todos"
    for group_name, group_entries in groups.items():
        if group_name:
            print(f"\n  {group_name}")
            print(f"  {'─' * len(group_name)}")
        else:
            print()

        for entry in group_entries:
            # Load state from state.json
            state_path = todos_root / entry.slug / "state.json"
            phase = "?"
            if state_path.exists():
                try:
                    state = json.loads(state_path.read_text())
                    phase = state.get("phase", "?")
                except (json.JSONDecodeError, OSError):
                    pass

            deps_str = ""
            if entry.after:
                deps_str = f"  (after: {', '.join(entry.after)})"

            print(f"    {entry.slug}  [{phase}]{deps_str}")


def _handle_roadmap_add(args: list[str]) -> None:
    """Handle telec roadmap add <slug> [--group G] [--after d1,d2] [--description T] [--before S]."""
    from teleclaude.core.next_machine.core import add_to_roadmap

    if not args or args[0] in ("--help", "-h"):
        print(_roadmap_usage())
        return

    slug: str | None = None
    project_root = Path.cwd()
    group: str | None = None
    after: list[str] | None = None
    description: str | None = None
    before: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--project-root" and i + 1 < len(args):
            project_root = Path(args[i + 1]).expanduser().resolve()
            i += 2
        elif arg == "--group" and i + 1 < len(args):
            group = args[i + 1]
            i += 2
        elif arg == "--after" and i + 1 < len(args):
            after = [p.strip() for p in args[i + 1].split(",") if p.strip()]
            i += 2
        elif arg == "--description" and i + 1 < len(args):
            description = args[i + 1]
            i += 2
        elif arg == "--before" and i + 1 < len(args):
            before = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_roadmap_usage())
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                print(_roadmap_usage())
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_roadmap_usage())
        raise SystemExit(1)

    add_to_roadmap(str(project_root), slug, group=group, after=after, description=description, before=before)
    print(f"Added {slug} to roadmap.")


def _handle_roadmap_remove(args: list[str]) -> None:
    """Handle telec roadmap remove <slug>."""
    from teleclaude.core.next_machine.core import remove_from_roadmap

    if not args or args[0] in ("--help", "-h"):
        print(_roadmap_usage())
        return

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
            print(_roadmap_usage())
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_roadmap_usage())
        raise SystemExit(1)

    if remove_from_roadmap(str(project_root), slug):
        print(f"Removed {slug} from roadmap.")
    else:
        print(f"Slug not found in roadmap: {slug}")
        raise SystemExit(1)


def _handle_roadmap_move(args: list[str]) -> None:
    """Handle telec roadmap move <slug> --before <s> | --after <s>."""
    from teleclaude.core.next_machine.core import move_in_roadmap

    if not args or args[0] in ("--help", "-h"):
        print(_roadmap_usage())
        return

    slug: str | None = None
    project_root = Path.cwd()
    before: str | None = None
    after: str | None = None

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--project-root" and i + 1 < len(args):
            project_root = Path(args[i + 1]).expanduser().resolve()
            i += 2
        elif arg == "--before" and i + 1 < len(args):
            before = args[i + 1]
            i += 2
        elif arg == "--after" and i + 1 < len(args):
            after = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_roadmap_usage())
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_roadmap_usage())
        raise SystemExit(1)

    if not before and not after:
        print("Either --before or --after is required.")
        print(_roadmap_usage())
        raise SystemExit(1)

    if move_in_roadmap(str(project_root), slug, before=before, after=after):
        target = before or after
        direction = "before" if before else "after"
        print(f"Moved {slug} {direction} {target}.")
    else:
        print(f"Slug not found in roadmap: {slug}")
        raise SystemExit(1)


def _handle_roadmap_deps(args: list[str]) -> None:
    """Handle telec roadmap deps <slug> --after dep1,dep2."""
    from teleclaude.core.next_machine.core import load_roadmap, save_roadmap

    if not args or args[0] in ("--help", "-h"):
        print(_roadmap_usage())
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
            after = [p.strip() for p in args[i + 1].split(",") if p.strip()]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_roadmap_usage())
            raise SystemExit(1)
        else:
            if slug is not None:
                print("Only one slug is allowed.")
                raise SystemExit(1)
            slug = arg
            i += 1

    if not slug:
        print("Missing required slug.")
        print(_roadmap_usage())
        raise SystemExit(1)

    if after is None:
        print("--after is required.")
        print(_roadmap_usage())
        raise SystemExit(1)

    cwd = str(project_root)
    entries = load_roadmap(cwd)
    found = False
    for entry in entries:
        if entry.slug == slug:
            entry.after = after
            found = True
            break

    if not found:
        print(f"Slug not found in roadmap: {slug}")
        raise SystemExit(1)

    save_roadmap(cwd, entries)
    if after:
        print(f"Set dependencies for {slug}: {', '.join(after)}")
    else:
        print(f"Cleared dependencies for {slug}.")


def _roadmap_usage() -> str:
    """Return usage string for telec roadmap."""
    return (
        "Usage:\n"
        "  telec roadmap                                   # Show roadmap (grouped, with state)\n"
        "  telec roadmap add <slug> [options]               # Add entry to roadmap\n"
        "  telec roadmap remove <slug>                      # Remove entry from roadmap\n"
        "  telec roadmap move <slug> --before <s>           # Reorder: move before another\n"
        "  telec roadmap move <slug> --after <s>            # Reorder: move after another\n"
        "  telec roadmap deps <slug> --after dep1,dep2      # Set dependencies\n"
        "\n"
        "Add options:\n"
        "  --group GROUP          Visual grouping label\n"
        "  --after dep1,dep2      Comma-separated dependency slugs\n"
        "  --before <slug>        Insert before this slug (default: append)\n"
        "  --description TEXT     Summary description\n"
        "  --project-root PATH    Project root directory\n"
    )


def _handle_config(args: list[str]) -> None:
    """Handle telec config command.

    No args → interactive menu (TUI). Subcommands (get/patch/validate) → delegate
    to existing config_cmd handler for daemon config.
    """
    if args and args[0] in ("--help", "-h"):
        print(_config_usage())
        return

    if not args:
        if not sys.stdin.isatty():
            print("Error: Interactive config requires a terminal.")
            raise SystemExit(1)

        _run_tui_config_mode(guided=False)
        return

    subcommand = args[0]
    if subcommand in ("get", "patch"):
        from teleclaude.cli.config_cmd import handle_config_command

        handle_config_command(args)
    elif subcommand in ("people", "env", "notify", "validate", "invite"):
        from teleclaude.cli.config_cli import handle_config_cli

        handle_config_cli(args)
    else:
        print(f"Unknown config subcommand: {subcommand}")
        print(_config_usage())
        raise SystemExit(1)


def _handle_onboard(args: list[str]) -> None:
    """Handle telec onboard command."""
    if args and args[0] in ("--help", "-h"):
        print(_onboard_usage())
        return

    if not sys.stdin.isatty():
        print("Error: Onboarding wizard requires a terminal.")
        raise SystemExit(1)

    _run_tui_config_mode(guided=True)


def _config_usage() -> str:
    """Return usage string for telec config."""
    return (
        "Usage:\n"
        "  telec config                                   # Interactive menu\n"
        "  telec config get [paths...]                    # Get daemon config values\n"
        "  telec config patch [options]                   # Patch daemon config\n"
        "\n"
        "  telec config people list [--json]              # List people\n"
        "  telec config people add --name X [--email Y] [--role Z] [--telegram-user U] [--telegram-id ID]\n"
        "  telec config people edit NAME [--role Z] [--email Y] [--telegram-user U] [--telegram-id ID]\n"
        "  telec config people remove NAME [--delete-dir]\n"
        "\n"
        "  telec config env list [--json]                 # Show env var status\n"
        "  telec config env set KEY=VALUE [KEY=VALUE ...] # Set env vars in .env\n"
        "\n"
        "  telec config notify NAME --telegram on|off     # Toggle notifications\n"
        "  telec config validate [--json]                 # Full validation\n"
        "  telec config invite NAME [--adapters telegram] # Generate invite links\n"
    )


def _onboard_usage() -> str:
    """Return usage string for telec onboard."""
    return (
        "Usage:\n"
        "  telec onboard                  # Guided onboarding wizard\n"
        "\n"
        "Walks through all configuration in order.\n"
        "Detects existing config and skips completed sections.\n"
    )


if __name__ == MAIN_MODULE:
    main()
