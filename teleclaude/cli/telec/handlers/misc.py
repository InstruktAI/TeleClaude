"""Miscellaneous handlers: version, revive, computers, projects, tmux helpers."""

from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
from typing import TYPE_CHECKING

from teleclaude.cli.telec import flags as F
from teleclaude.cli.telec._shared import TMUX_ENV_KEY, TUI_ENV_KEY, TUI_SESSION_NAME
from teleclaude.cli.telec.handlers._arg_parsing import parse_command_args
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.telec.surface import SESSIONS_REVIVE
from teleclaude.config.machine import config
from teleclaude.constants import ENV_ENABLE
from teleclaude.git import InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.paths import REPO_ROOT
from teleclaude.project_root import resolve_invocation_cwd

if TYPE_CHECKING:
    from teleclaude.api_models import CreateSessionResponseDTO

_UNKNOWN_CHANNEL = "unknown"

__all__ = [
    "_attach_tmux_session",
    "_ensure_tmux_mouse_on",
    "_ensure_tmux_status_hidden_for_tui",
    "_git_short_commit_hash",
    "_handle_computers",
    "_handle_projects",
    "_handle_revive",
    "_handle_version",
    "_maybe_kill_tui_session",
    "_revive_session",
    "_revive_session_via_api",
    "_send_revive_enter_via_api",
]


def _teleclaude_version() -> str:
    result: str = importlib.import_module("teleclaude").__version__
    return result


def _handle_tool_command(name: str, args: list[str]) -> None:
    importlib.import_module("teleclaude.cli.tool_commands.infra").__dict__[name](args)


def _git_short_commit_hash() -> str:
    """Return HEAD short hash, or 'unknown' when unavailable."""
    try:
        repo = Repo(REPO_ROOT, search_parent_directories=True)
        short_hash = repo.head.commit.hexsha[:7]
        return short_hash if short_hash else "unknown"
    except (InvalidGitRepositoryError, NoSuchPathError, ValueError, OSError):
        return "unknown"


def _handle_version() -> None:
    """Print runtime version metadata."""
    commit_hash = _git_short_commit_hash()
    try:
        channel = str(importlib.import_module("teleclaude.config.machine").config.deployment.channel)
    except (AttributeError, OSError, TypeError, ValueError):
        channel = _UNKNOWN_CHANNEL

    print(f"TeleClaude v{_teleclaude_version()} (channel: {channel}, commit: {commit_hash})")


def _handle_revive(args: list[str]) -> None:
    """Handle telec sessions revive command."""
    if not args:
        print(_usage("sessions", "revive"))
        return

    parsed = parse_command_args(SESSIONS_REVIVE, args)
    positionals = parsed.positionals
    if len(positionals) > 1:
        print("Only one session_id is allowed.")
        print(_usage("sessions", "revive"))
        raise SystemExit(1)
    session_id = positionals[0] if positionals else None
    if not session_id:
        print("Missing required session_id.")
        print(_usage("sessions", "revive"))
        raise SystemExit(1)

    attach = parsed.has(F.FLAG_REVIVE_ATTACH)
    agent = parsed.value(F.FLAG_REVIVE_AGENT)
    computer = parsed.value(F.FLAG_COMPUTER)

    _revive_session(session_id, attach, agent=agent, computer=computer)


def _revive_session(
    session_id: str,
    attach: bool,
    *,
    agent: str | None = None,
    computer: str | None = None,
) -> None:
    """Revive a session by TeleClaude or native session ID."""
    APIError = importlib.import_module("teleclaude.cli.api_client").APIError
    try:
        result = asyncio.run(_revive_session_via_api(session_id, agent=agent, computer=computer))
    except APIError as e:
        e.exit_if_not_accepted()
        print(f"Error: {e}")
        raise SystemExit(1) from e

    if result.status != "success":
        print(result.error or "Revive failed")
        raise SystemExit(1)

    print(f"Revived session {result.session_id}")
    try:
        asyncio.run(_send_revive_enter_via_api(result.session_id, computer=result.computer or computer))
    except APIError as e:
        print(f"Warning: revive kick failed: {e}")
    if attach and result.tmux_session_name:
        _attach_tmux_session(result.tmux_session_name)


async def _revive_session_via_api(
    session_id: str,
    *,
    agent: str | None = None,
    computer: str | None = None,
) -> CreateSessionResponseDTO:
    """Revive a session via API and return the response."""
    from teleclaude.cli.api_client import TelecAPIClient  # noqa: PLC0415 - revive owns its API client.

    api = TelecAPIClient()
    await api.connect()
    try:
        project = str(resolve_invocation_cwd()) if agent else None
        return await api.revive_session(session_id, agent=agent, project=project, computer=computer)
    finally:
        await api.close()


async def _send_revive_enter_via_api(session_id: str, *, computer: str | None = None) -> bool:
    """Send an enter key after revive so headless activity resumes immediately."""
    from teleclaude.cli.api_client import TelecAPIClient  # noqa: PLC0415 - revive owns its API client.

    api = TelecAPIClient()
    await api.connect()
    try:
        return await api.send_keys(
            session_id=session_id,
            computer=computer or config.computer.name,
            key="enter",
            count=1,
        )
    finally:
        await api.close()


def _attach_tmux_session(tmux_session_name: str) -> None:
    """Attach or switch to a tmux session."""
    tmux = config.computer.tmux_binary
    if os.environ.get("TMUX"):  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
        subprocess.run([tmux, "switch-client", "-t", tmux_session_name], check=False)
        return

    os.execlp(tmux, tmux, "attach-session", "-t", tmux_session_name)


def _handle_computers(args: list[str]) -> None:
    """Handle telec computers commands."""
    if not args:
        print(_usage("computers"))
        return
    if args[0] in ("-h", "--help"):
        print(_usage("computers"))
        return

    subcommand = args[0]
    if subcommand == "list":
        _handle_tool_command("handle_computers", args[1:])
        return
    print(f"Unknown computers subcommand: {subcommand}")
    print(_usage("computers"))
    raise SystemExit(1)


_ACTIVE_COMPUTER_SUBCOMMAND = "active-computer"
_ACTIVE_COMPUTER_HANDLER = "handle_projects_active_computer"


def _handle_projects(args: list[str]) -> None:
    """Handle telec projects commands."""
    if not args:
        print(_usage("projects"))
        return
    if args[0] in ("-h", "--help"):
        print(_usage("projects"))
        return

    subcommand = args[0]
    if subcommand == "list":
        _handle_tool_command("handle_projects", args[1:])
        return
    if subcommand == _ACTIVE_COMPUTER_SUBCOMMAND:
        _handle_tool_command(_ACTIVE_COMPUTER_HANDLER, args[1:])
        return
    print(f"Unknown projects subcommand: {subcommand}")
    print(_usage("projects"))
    raise SystemExit(1)


def _maybe_kill_tui_session() -> None:
    """Kill the tc_tui tmux session if telec created it."""
    if os.environ.get(TUI_ENV_KEY) != ENV_ENABLE:  # fmt: skip  # guard: direct-env-read - allowed: bootstrap or internal process signal
        return
    if not os.environ.get(TMUX_ENV_KEY):  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
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
    if not os.environ.get(TMUX_ENV_KEY):  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
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
    if not os.environ.get(TMUX_ENV_KEY):  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
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
