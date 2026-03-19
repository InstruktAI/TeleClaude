"""Miscellaneous handlers: version, sync, watch, revive, computers, projects, tmux helpers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from teleclaude import __version__
from teleclaude.cli.session_revive import (
    attach_tmux_session as _attach_tmux_session,
)
from teleclaude.cli.session_revive import (
    handle_revive_command as _handle_revive,
)
from teleclaude.cli.session_revive import (
    revive_session as _revive_session,
)
from teleclaude.cli.session_revive import (
    revive_session_via_api as _revive_session_via_api,
)
from teleclaude.cli.session_revive import (
    send_revive_enter_via_api as _send_revive_enter_via_api,
)
from teleclaude.cli.telec._shared import TMUX_ENV_KEY, TUI_ENV_KEY, TUI_SESSION_NAME, config
from teleclaude.cli.telec.help import _usage
from teleclaude.cli.tool_commands.infra import handle_computers, handle_projects
from teleclaude.cli.watch import run_watch
from teleclaude.config.loader import load_project_config
from teleclaude.constants import ENV_ENABLE
from teleclaude.git import InvalidGitRepositoryError, NoSuchPathError, Repo
from teleclaude.sync import sync
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
        repo = Repo(Path.cwd(), search_parent_directories=True)
        short_hash = repo.head.commit.hexsha[:7]
        return short_hash if short_hash else "unknown"
    except (InvalidGitRepositoryError, NoSuchPathError, ValueError, OSError):
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

    ok = sync(project_root, validate_only=validate_only, warn_only=warn_only)
    if not ok:
        raise SystemExit(1)


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
