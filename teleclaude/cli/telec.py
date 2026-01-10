"""telec: TUI client for TeleClaude."""

import asyncio
import curses
import os
import subprocess
import sys

from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.config import config


def main() -> None:
    """Main entry point for telec CLI."""
    argv = sys.argv[1:]

    if argv and argv[0].startswith("/"):
        _handle_cli_command(argv)
        return

    # TUI mode - ensure we're in tmux for pane preview
    if not os.environ.get("TMUX"):
        # Check if TUI session already exists - adopt it instead of creating new
        tmux = config.computer.tmux_binary
        result = subprocess.run(
            [tmux, "has-session", "-t", "tc_tui"],
            capture_output=True,
        )
        if result.returncode == 0:
            # Existing TUI found - attach to it
            os.execlp(tmux, tmux, "attach", "-t", "tc_tui")
        else:
            # No TUI running - create new named session
            os.execlp(tmux, tmux, "new-session", "-s", "tc_tui", "telec")

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
        await app.initialize()
        curses.wrapper(app.run)
    except KeyboardInterrupt:
        pass  # Clean exit on Ctrl-C
    finally:
        await api.close()


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
        _quick_start(cmd, mode, prompt)  # Sync - spawns tmux directly
    else:
        print(f"Unknown command: /{cmd}")
        print(_usage())


async def _list_sessions(api: TelecAPIClient) -> None:
    """List sessions to stdout.

    Args:
        api: API client
    """
    await api.connect()
    try:
        sessions = await api.list_sessions()
        for session in sessions:
            computer = session.get("computer", "?")
            agent = session.get("active_agent", "?")
            mode = session.get("thinking_mode", "?")
            title = session.get("title", "Untitled")
            print(f"{computer}: {agent}/{mode} - {title}")
    finally:
        await api.close()


def _quick_start(agent: str, mode: str, prompt: str | None) -> None:
    """Quick start a session by spawning tmux directly.

    Args:
        agent: Agent name (claude, gemini, codex)
        mode: Thinking mode (fast, med, slow)
        prompt: Initial prompt (optional - if None, starts interactive session)
    """
    import shlex
    import uuid

    from teleclaude.core.agents import get_agent_command

    # Generate session name
    session_id = str(uuid.uuid4())[:8]
    tmux_name = f"tc_{session_id}"
    working_dir = os.getcwd()
    tmux = config.computer.tmux_binary

    # Create tmux session
    result = subprocess.run(
        [tmux, "new-session", "-d", "-s", tmux_name, "-c", working_dir],
        capture_output=True,
    )
    if result.returncode != 0:
        print(f"Failed to create tmux session: {result.stderr.decode()}")
        return

    # Build agent command using existing infrastructure
    try:
        agent_cmd = get_agent_command(agent, thinking_mode=mode, interactive=bool(prompt))
    except ValueError as e:
        print(f"Error: {e}")
        return

    # Add prompt if provided
    if prompt:
        agent_cmd += f" {shlex.quote(prompt)}"

    # Send agent command to tmux
    subprocess.run([tmux, "send-keys", "-t", tmux_name, agent_cmd, "Enter"], check=False)

    # Attach to session
    os.execlp(tmux, tmux, "attach", "-t", tmux_name)


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
