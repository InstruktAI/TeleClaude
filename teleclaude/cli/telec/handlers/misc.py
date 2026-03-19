"""Miscellaneous handlers: version, sync, watch, revive, computers, projects, tmux helpers."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from pathlib import Path

import teleclaude.git as git
import teleclaude.sync as sync_module
from teleclaude import __version__
from teleclaude.cli import session_revive
from teleclaude.cli.api_client import APIError
from teleclaude.cli.models import CreateSessionResult
from teleclaude.cli.telec._shared import TMUX_ENV_KEY, TUI_ENV_KEY, TUI_SESSION_NAME, config
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.tool_commands.infra import handle_computers, handle_projects
from teleclaude.cli.watch import run_watch
from teleclaude.config.loader import load_project_config
from teleclaude.constants import ENV_ENABLE
from teleclaude.utils import resolve_project_config_path

__all__ = [
    "_attach_tmux_session",
    "_ensure_tmux_mouse_on",
    "_ensure_tmux_status_hidden_for_tui",
    "_git_short_commit_hash",
    "_handle_computers",
    "_handle_projects",
    "_handle_revive",
    "_handle_sync",
    "_handle_version",
    "_handle_watch",
    "_maybe_kill_tui_session",
    "_revive_session",
    "_revive_session_via_api",
    "_send_revive_enter_via_api",
]


def _git_short_commit_hash() -> str:
    """Return HEAD short hash, or 'unknown' when unavailable."""
    try:
        repo = git.Repo(Path.cwd(), search_parent_directories=True)
        short_hash = repo.head.commit.hexsha[:7]
        return short_hash if short_hash else "unknown"
    except (git.InvalidGitRepositoryError, git.NoSuchPathError, ValueError, OSError):
        return "unknown"


def _handle_version() -> None:
    """Print runtime version metadata."""
    commit_hash = _git_short_commit_hash()
    project_root = Path(__file__).resolve().parents[4]
    try:
        project_cfg_path = resolve_project_config_path(project_root)
        project_config = load_project_config(project_cfg_path)
        channel = project_config.deployment.channel
        pinned_minor = project_config.deployment.pinned_minor
    except Exception:
        channel = "alpha"
        pinned_minor = ""

    channel_str = f"{channel} ({pinned_minor})" if channel == "stable" and pinned_minor else channel
    print(f"TeleClaude v{__version__} (channel: {channel_str}, commit: {commit_hash})")


def _handle_sync(args: list[str]) -> None:
    """Handle telec sync command."""
    project_root = Path.cwd()
    warn_only = False
    validate_only = False

    i = 0
    while i < len(args):
        if args[i] == "--warn-only":
            warn_only = True
            i += 1
        elif args[i] == "--validate-only":
            validate_only = True
            i += 1
        else:
            i += 1

    active_sync_module = sys.modules.get("teleclaude.sync", sync_module)
    ok = active_sync_module.sync(project_root, validate_only=validate_only, warn_only=warn_only)
    if not ok:
        raise SystemExit(1)


def _handle_revive(args: list[str]) -> None:
    """Handle `telec sessions revive` while preserving local patch points."""
    if not args:
        print(_usage("sessions", "revive"))
        return

    attach = False
    agent: str | None = None
    session_id: str | None = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--attach":
            attach = True
            i += 1
        elif arg == "--agent":
            if i + 1 >= len(args):
                print("--agent requires a value.")
                print(_usage("sessions", "revive"))
                raise SystemExit(1)
            agent = args[i + 1]
            i += 2
        elif arg.startswith("-"):
            print(f"Unknown option: {arg}")
            print(_usage("sessions", "revive"))
            raise SystemExit(1)
        else:
            if session_id is not None:
                print("Only one session_id is allowed.")
                print(_usage("sessions", "revive"))
                raise SystemExit(1)
            session_id = arg
            i += 1

    if not session_id:
        print("Missing required session_id.")
        print(_usage("sessions", "revive"))
        raise SystemExit(1)

    _revive_session(session_id, attach, agent=agent)


def _revive_session(session_id: str, attach: bool, *, agent: str | None = None) -> None:
    """Revive a session by TeleClaude or native session ID."""
    try:
        result = asyncio.run(_revive_session_via_api(session_id, agent=agent))
    except APIError as exc:
        print(f"Error: {exc}")
        return

    if getattr(result, "status", None) != "success":
        print(getattr(result, "error", None) or "Revive failed")
        return

    print(f"Revived session {result.session_id}")
    try:
        asyncio.run(_send_revive_enter_via_api(result.session_id))
    except APIError as exc:
        print(f"Warning: revive kick failed: {exc}")
    if attach and getattr(result, "tmux_session_name", None):
        _attach_tmux_session(result.tmux_session_name)


async def _revive_session_via_api(session_id: str, *, agent: str | None = None) -> CreateSessionResult:
    """Delegate revive API call through the extracted session-revive module."""
    return await session_revive.revive_session_via_api(session_id, agent=agent)


async def _send_revive_enter_via_api(session_id: str) -> bool:
    """Delegate revive-enter API call through the extracted session-revive module."""
    return await session_revive.send_revive_enter_via_api(session_id)


def _attach_tmux_session(tmux_session_name: str) -> None:
    """Attach or switch to a tmux session."""
    session_revive.attach_tmux_session(tmux_session_name)


def _handle_watch(args: list[str]) -> None:
    """Handle telec watch command."""
    run_watch(Path.cwd())


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
        handle_computers(args[1:])
    else:
        print(f"Unknown computers subcommand: {subcommand}")
        print(_usage("computers"))
        raise SystemExit(1)


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
        handle_projects(args[1:])
    else:
        print(f"Unknown projects subcommand: {subcommand}")
        print(_usage("projects"))
        raise SystemExit(1)


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
