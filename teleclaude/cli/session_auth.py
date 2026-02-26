"""TTY-scoped login state helpers for ``telec auth``."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_AUTH_DIR = Path("~/.teleclaude/auth").expanduser()
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class SessionAuthContext:
    """Resolved terminal context used for per-TTY auth state."""

    tty: str
    auth_path: Path


@dataclass(frozen=True)
class SessionAuthState:
    """Stored login email and the associated TTY context."""

    email: str
    context: SessionAuthContext


def _resolve_tty() -> str | None:
    """Return the active TTY path when available."""
    try:
        return os.ttyname(sys.stdin.fileno())
    except OSError:
        return None


def _auth_path_for_tty(tty: str) -> Path:
    """Map a TTY path to a stable filename under ~/.teleclaude/auth."""
    safe_name = tty.strip().replace("/", "_")
    return _AUTH_DIR / f"{safe_name}.email"


def _normalize_email(email: str) -> str:
    """Normalize and validate a login email."""
    normalized = email.strip().lower()
    if not _EMAIL_PATTERN.fullmatch(normalized):
        raise ValueError("invalid email format")
    return normalized


def get_current_session_context() -> SessionAuthContext | None:
    """Return current TTY context, or None when no TTY is attached."""
    tty = _resolve_tty()
    if tty is None:
        return None
    return SessionAuthContext(tty=tty, auth_path=_auth_path_for_tty(tty))


def write_current_session_email(email: str) -> SessionAuthState:
    """Persist login email for the current TTY."""
    context = get_current_session_context()
    if context is None:
        raise ValueError("no terminal session detected (TTY unavailable)")

    normalized_email = _normalize_email(email)
    context.auth_path.parent.mkdir(parents=True, exist_ok=True)
    context.auth_path.write_text(f"{normalized_email}\n", encoding="utf-8")
    return SessionAuthState(email=normalized_email, context=context)


def read_current_session_email() -> str | None:
    """Read current TTY login email, if present."""
    context = get_current_session_context()
    if context is None:
        return None
    try:
        email = context.auth_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return email or None


def clear_current_session_email() -> bool:
    """Remove current TTY login email file."""
    context = get_current_session_context()
    if context is None:
        return False
    try:
        context.auth_path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
