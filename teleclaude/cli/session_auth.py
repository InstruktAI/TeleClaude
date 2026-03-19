"""Terminal auth helpers for telec login and caller role resolution."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from teleclaude.cli.api_client import TelecAPIClient
from teleclaude.cli.session_identity import (
    AUTH_PATH,
    SESSION_AUTH_DIR,
    TUI_AUTH_EMAIL_ENV_KEY,
    TUI_SESSION_ENV_KEY,
    TerminalAuthState,
    TerminalSessionContext,
    clear_current_session_email,
    get_current_session_context,
    in_tmux_context,
    read_current_session_email,
    write_current_session_email,
)
from teleclaude.core.identity import get_identity_resolver

__all__ = [
    "AUTH_PATH",
    "SESSION_AUTH_DIR",
    "TUI_AUTH_EMAIL_ENV_KEY",
    "TUI_SESSION_ENV_KEY",
    "TerminalAuthState",
    "TerminalSessionContext",
    "clear_current_session_email",
    "get_current_session_context",
    "in_tmux_context",
    "read_current_session_email",
    "resolve_cli_caller_role",
    "write_current_session_email",
]


def resolve_cli_caller_role() -> str | None:
    """Resolve the effective human role for the current CLI caller.

    Two paths (tried in order):
    1. TTY auth: terminal human logged in via ``telec auth login``.
    2. Daemon API: dual-factor auth (session_id + tmux session name).

    Returns the effective human role, or None if unidentifiable.
    """
    # Path 1: TTY auth file → IdentityResolver
    email = read_current_session_email()
    if email:
        resolver = get_identity_resolver()
        person = resolver._by_email.get(email.lower())
        if person:
            return resolver._normalize_role(person.role)

    # Path 2: daemon API — works for any TeleClaude-managed session
    tmpdir = os.environ.get("TMPDIR", "")
    if not tmpdir:
        return None
    session_id_path = Path(tmpdir) / "teleclaude_session_id"
    if not session_id_path.exists():
        return None

    try:

        async def _fetch() -> str | None:
            api = TelecAPIClient()
            await api.connect()
            try:
                data = await api.get_auth_whoami()
            finally:
                await api.close()
            return data.get("role")

        return asyncio.run(_fetch())
    except Exception:
        return None
