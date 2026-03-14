"""Terminal auth state for telec login — single global identity file."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SESSION_AUTH_DIR = Path("~/.local/state/telec/session-auth").expanduser()
AUTH_PATH = SESSION_AUTH_DIR / "identity.json"
TUI_SESSION_ENV_KEY = "TELEC_TUI_SESSION"
TUI_AUTH_EMAIL_ENV_KEY = "TELEC_AUTH_EMAIL"


@dataclass(frozen=True)
class TerminalSessionContext:
    """Retained for API compatibility — no longer TTY-scoped."""

    tty: str
    key: str
    auth_path: Path


@dataclass(frozen=True)
class TerminalAuthState:
    """Stored terminal auth state."""

    email: str
    context: TerminalSessionContext


def in_tmux_context() -> bool:
    """Return True when running inside tmux."""
    return bool((os.environ.get("TMUX") or "").strip())


def get_current_session_context() -> TerminalSessionContext | None:
    """Return a context pointing at the global auth file."""
    return TerminalSessionContext(tty="", key="global", auth_path=AUTH_PATH)


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def read_current_session_email() -> str | None:
    """Read login email.

    Resolution order:
    1. TELEC_AUTH_EMAIL env var (set at TUI launch for tc_tui sessions)
    2. Global identity file written by ``telec auth login``
    """
    env_email = (os.environ.get(TUI_AUTH_EMAIL_ENV_KEY) or "").strip()
    if env_email:
        return _normalize_email(env_email) or None

    try:
        payload = AUTH_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return _normalize_email(payload) or None
    if not isinstance(data, dict):
        return None
    raw_email = data.get("email")
    if not isinstance(raw_email, str):
        return None
    return _normalize_email(raw_email) or None


def write_current_session_email(email: str) -> TerminalAuthState:
    """Write login email to the global identity file."""
    normalized_email = _normalize_email(email)
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("A valid email address is required.")

    SESSION_AUTH_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(SESSION_AUTH_DIR, 0o700)
    except OSError:
        pass

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload = {"email": normalized_email, "updated_at": now}

    tmp_path = AUTH_PATH.with_name(f"identity.{os.getpid()}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as tmp:
        json.dump(payload, tmp, sort_keys=True)
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
    try:
        os.chmod(tmp_path, 0o600)
    except OSError:
        pass
    os.replace(tmp_path, AUTH_PATH)
    try:
        os.chmod(AUTH_PATH, 0o600)
    except OSError:
        pass

    context = TerminalSessionContext(tty="", key="global", auth_path=AUTH_PATH)
    return TerminalAuthState(email=normalized_email, context=context)


def clear_current_session_email() -> bool:
    """Delete the global identity file."""
    try:
        AUTH_PATH.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
