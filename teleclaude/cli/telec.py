"""telec: TUI client for TeleClaude."""

import asyncio
import curses
import hashlib
import os
import subprocess
import sys
from enum import Enum
from pathlib import Path

from teleclaude.cli.api_client import APIError, TelecAPIClient
from teleclaude.cli.models import CreateSessionResult
from teleclaude.config import config
from teleclaude.constants import ENV_ENABLE, MAIN_MODULE
from teleclaude.logging_config import setup_logging

TMUX_ENV_KEY = "TMUX"
TUI_ENV_KEY = "TELEC_TUI_SESSION"
TUI_SESSION_NAME = "tc_tui"


class TelecCommand(str, Enum):
    """Supported telec CLI commands."""

    LIST = "list"
    CLAUDE = "claude"
    GEMINI = "gemini"
    CODEX = "codex"
    INIT = "init"


def main() -> None:
    """Main entry point for telec CLI."""
    setup_logging()
    argv = sys.argv[1:]

    if argv and argv[0].startswith("/"):
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
        asyncio.run(_run_tui())
    except KeyboardInterrupt:
        pass  # Clean exit on Ctrl-C


async def _run_tui() -> None:
    """Run TUI application."""
    # Lazy import: TelecApp applies nest_asyncio which breaks httpx for CLI commands
    from teleclaude.cli.tui.app import TelecApp

    api = TelecAPIClient()
    app = TelecApp(api)

    try:
        _ensure_tmux_mouse_on()
        await app.initialize()
        curses.wrapper(app.run)
    except KeyboardInterrupt:
        pass  # Clean exit on Ctrl-C
    finally:
        await api.close()
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
        _quick_start(cmd_enum.value, mode, prompt)  # Sync - spawns tmux via daemon
    elif cmd_enum is TelecCommand.INIT:
        _init_project(Path.cwd())
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


def _init_project(project_root: Path) -> None:
    _sync_project_artifacts(project_root)
    _install_docs_watch(project_root)
    print("telec init complete.")


def _sync_project_artifacts(project_root: Path) -> None:
    commands = [
        [
            "uv",
            "run",
            "--quiet",
            "scripts/build_snippet_index.py",
            "--project-root",
            str(project_root),
        ],
        [
            "uv",
            "run",
            "--quiet",
            "bin/distribute.py",
            "--project-root",
            str(project_root),
            "--deploy",
        ],
    ]
    for cmd in commands:
        subprocess.run(cmd, cwd=project_root, check=True)


def _install_docs_watch(project_root: Path) -> None:
    if sys.platform == "darwin":
        _install_launchd_watch(project_root)
        return
    if sys.platform.startswith("linux"):
        _install_systemd_watch(project_root)
        return
    print("telec init: unsupported OS for auto-sync watcher.")


def _install_launchd_watch(project_root: Path) -> None:
    label = f"ai.instrukt.teleclaude.docs.{_project_hash(project_root)}"
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"
    plist_path.parent.mkdir(parents=True, exist_ok=True)

    command = (
        f"cd {project_root} && "
        f"uv run --quiet scripts/build_snippet_index.py --project-root {project_root} && "
        f"uv run --quiet bin/distribute.py --project-root {project_root} --deploy"
    )
    watch_paths = [
        project_root / ".agents",
        project_root / "docs",
        project_root / "agents" / "docs",
        project_root / "teleclaude.yml",
    ]
    watch_entries = "\n".join(f"        <string>{path}</string>" for path in watch_paths)
    launchd_path = os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
      <string>/bin/zsh</string>
      <string>-lc</string>
      <string>{command}</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
      <key>PATH</key>
      <string>{launchd_path}</string>
    </dict>
    <key>WatchPaths</key>
    <array>
{watch_entries}
    </array>
    <key>RunAtLoad</key>
    <true/>
  </dict>
</plist>
"""
    plist_path.write_text(plist_content, encoding="utf-8")

    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", domain, str(plist_path)], check=False, capture_output=True)
    if subprocess.run(["launchctl", "bootstrap", domain, str(plist_path)], check=False).returncode != 0:
        subprocess.run(["launchctl", "load", str(plist_path)], check=False)


def _install_systemd_watch(project_root: Path) -> None:
    unit_id = f"teleclaude-docs-{_project_hash(project_root)}"
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    service_path = unit_dir / f"{unit_id}.service"
    path_path = unit_dir / f"{unit_id}.path"

    command = (
        f"cd {project_root} && "
        f"uv run --quiet scripts/build_snippet_index.py --project-root {project_root} && "
        f"uv run --quiet bin/distribute.py --project-root {project_root} --deploy"
    )
    service_content = f"""[Unit]
Description=TeleClaude docs sync ({project_root})

[Service]
Type=oneshot
WorkingDirectory={project_root}
ExecStart=/bin/bash -lc '{command}'
"""
    path_content = f"""[Unit]
Description=TeleClaude docs watch ({project_root})

[Path]
PathModified={project_root}/.agents
PathModified={project_root}/docs
PathModified={project_root}/agents/docs
PathModified={project_root}/teleclaude.yml
Unit={unit_id}.service

[Install]
WantedBy=default.target
"""
    service_path.write_text(service_content, encoding="utf-8")
    path_path.write_text(path_content, encoding="utf-8")

    if subprocess.run(["systemctl", "--user", "daemon-reload"], check=False).returncode != 0:
        print("telec init: systemd user services unavailable.")
        return
    subprocess.run(["systemctl", "--user", "enable", "--now", f"{unit_id}.path"], check=False)


def _project_hash(project_root: Path) -> str:
    digest = hashlib.sha1(str(project_root).encode("utf-8")).hexdigest()
    return digest[:10]


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


def _usage() -> str:
    """Return usage string.

    Returns:
        Usage text
    """
    return (
        "Usage:\n"
        "  telec                          # Open TUI (Sessions view)\n"
        "  telec /list                    # List sessions (stdout, no TUI)\n"
        "  telec /claude [mode] [prompt]  # Start Claude (mode: fast/med/slow, prompt optional)\n"
        "  telec /gemini [mode] [prompt]  # Start Gemini (mode: fast/med/slow, prompt optional)\n"
        "  telec /codex [mode] [prompt]   # Start Codex (mode: fast/med/slow/deep, prompt optional)\n"
        "  telec /init                    # Initialize docs sync and auto-rebuild watcher\n"
    )


if __name__ == MAIN_MODULE:
    main()
