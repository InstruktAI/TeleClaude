"""Shared session revive helpers for telec CLI surfaces."""

from __future__ import annotations

import asyncio
import os
import subprocess

from teleclaude.cli.api_client import APIError, TelecAPIClient
from teleclaude.cli.models import CreateSessionResult
from teleclaude.cli.telec._shared import config
from teleclaude.cli.telec.help import _usage

__all__ = [
    "attach_tmux_session",
    "handle_revive_command",
    "revive_session",
    "revive_session_via_api",
    "send_revive_enter_via_api",
]


def handle_revive_command(args: list[str]) -> None:
    """Handle `telec sessions revive`."""
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

    revive_session(session_id, attach, agent=agent)


def revive_session(session_id: str, attach: bool, *, agent: str | None = None) -> None:
    """Revive a session by TeleClaude or native session ID."""
    try:
        result = asyncio.run(revive_session_via_api(session_id, agent=agent))
    except APIError as exc:
        print(f"Error: {exc}")
        return

    if result.status != "success":
        print(result.error or "Revive failed")
        return

    print(f"Revived session {result.session_id}")
    try:
        asyncio.run(send_revive_enter_via_api(result.session_id))
    except APIError as exc:
        print(f"Warning: revive kick failed: {exc}")
    if attach and result.tmux_session_name:
        attach_tmux_session(result.tmux_session_name)


async def revive_session_via_api(session_id: str, *, agent: str | None = None) -> CreateSessionResult:
    """Revive a session via API and return the response."""
    api = TelecAPIClient()
    await api.connect()
    try:
        project = os.getcwd() if agent else None
        return await api.revive_session(session_id, agent=agent, project=project)
    finally:
        await api.close()


async def send_revive_enter_via_api(session_id: str) -> bool:
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


def attach_tmux_session(tmux_session_name: str) -> None:
    """Attach or switch to a tmux session."""
    tmux = config.computer.tmux_binary
    if os.environ.get("TMUX"):
        subprocess.run([tmux, "switch-client", "-t", tmux_session_name], check=False)
        return

    os.execlp(tmux, tmux, "attach-session", "-t", tmux_session_name)
