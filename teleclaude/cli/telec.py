"""telec: TUI client for TeleClaude."""

import asyncio
import curses
import os
import subprocess
import sys

from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.cli.tui.app import TelecApp
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

    api = TelecAPIClient()

    if cmd == "list":
        asyncio.run(_list_sessions(api))
    elif cmd in ("claude", "gemini", "codex"):
        mode = args[0] if args else "slow"
        prompt = " ".join(args[1:]) if len(args) > 1 else None
        asyncio.run(_quick_start(api, cmd, mode, prompt))
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


async def _quick_start(api: TelecAPIClient, agent: str, mode: str, prompt: str | None) -> None:
    """Quick start a session and attach.

    Args:
        api: API client
        agent: Agent name (claude, gemini, codex)
        mode: Thinking mode (fast, med, slow)
        prompt: Initial prompt
    """
    await api.connect()
    try:
        # Use current directory as project
        project_dir = os.getcwd()
        computer = "local"

        if not prompt:
            print("Error: prompt required")
            print("Usage: telec /claude slow 'your prompt here'")
            return

        result = await api.create_session(
            computer=computer,
            project_dir=project_dir,
            agent=agent,
            thinking_mode=mode,
            message=prompt,
        )

        tmux_session = result.get("tmux_session_name")
        if tmux_session:
            await api.close()
            # Attach to the tmux session
            subprocess.run([config.computer.tmux_binary, "attach", "-t", str(tmux_session)], check=False)
        else:
            print(f"Error: {result}")
    finally:
        if api.is_connected:  # Only close if not already closed
            await api.close()


def _usage() -> str:
    """Return usage string.

    Returns:
        Usage text
    """
    return (
        "Usage:\n"
        "  telec                          # Open TUI (Sessions view)\n"
        "  telec /list                    # List sessions (stdout, no TUI)\n"
        "  telec /claude [mode] [prompt]  # Start Claude session\n"
        "  telec /gemini [mode] [prompt]  # Start Gemini session\n"
        "  telec /codex [mode] [prompt]   # Start Codex session\n"
    )


if __name__ == "__main__":
    main()
