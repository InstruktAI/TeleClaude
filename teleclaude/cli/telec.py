"""telec: TUI client for TeleClaude."""

import asyncio
import curses
import os
import subprocess
import sys

from teleclaude.cli.api_client import APIError, TelecAPIClient
from teleclaude.cli.models import CreateSessionResult
from teleclaude.config import config
from teleclaude.logging_config import setup_logging


def main() -> None:
    """Main entry point for telec CLI."""
    setup_logging()
    argv = sys.argv[1:]

    if argv and argv[0].startswith("/"):
        _handle_cli_command(argv)
        return

    # TUI mode - ensure we're in tmux for pane preview
    if not os.environ.get("TMUX"):
        # Always restart the TUI session to avoid adopting stale panes
        tmux = config.computer.tmux_binary
        result = subprocess.run(
            [tmux, "has-session", "-t", "tc_tui"],
            capture_output=True,
        )
        if result.returncode == 0:
            subprocess.run(
                [tmux, "kill-session", "-t", "tc_tui"],
                check=False,
                capture_output=True,
            )
        # Create new named session and mark it as telec-managed
        tmux_args = [tmux, "new-session", "-s", "tc_tui", "-e", "TELEC_TUI_SESSION=1"]
        for key, value in os.environ.items():
            if key == "TELEC_TUI_SESSION":
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

    if cmd == "list":
        api = TelecAPIClient()
        asyncio.run(_list_sessions(api))
    elif cmd in ("claude", "gemini", "codex"):
        mode = args[0] if args else "slow"
        prompt = " ".join(args[1:]) if len(args) > 1 else None
        _quick_start(cmd, mode, prompt)  # Sync - spawns tmux via daemon
    else:
        print(f"Unknown command: /{cmd}")
        print(_usage())


def _maybe_kill_tui_session() -> None:
    """Kill the tc_tui tmux session if telec created it."""
    if os.environ.get("TELEC_TUI_SESSION") != "1":
        return
    if not os.environ.get("TMUX"):
        return

    tmux = config.computer.tmux_binary
    try:
        result = subprocess.run(
            [tmux, "display-message", "-p", "#S"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.stdout.strip() != "tc_tui":
            return
        subprocess.run(
            [tmux, "kill-session", "-t", "tc_tui"],
            check=False,
            capture_output=True,
        )
    except OSError:
        return


def _ensure_tmux_mouse_on() -> None:
    """Ensure tmux mouse is enabled for the current window."""
    if not os.environ.get("TMUX"):
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
    """Create a session via REST API and return the response."""
    api = TelecAPIClient()
    await api.connect()
    try:
        return await api.create_session(
            computer=config.computer.name,
            project_dir=os.getcwd(),
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
    )


if __name__ == "__main__":
    main()
