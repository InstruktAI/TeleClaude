"""TTY-scoped terminal auth state for telec login."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from teleclaude.constants import ENV_ENABLE

SESSION_AUTH_DIR = Path("~/.local/state/telec/session-auth").expanduser()
TUI_SESSION_ENV_KEY = "TELEC_TUI_SESSION"
TUI_AUTH_EMAIL_ENV_KEY = "TELEC_AUTH_EMAIL"


@dataclass(frozen=True)
class TerminalSessionContext:
    """Current terminal session identity context."""

    tty: str
    key: str
    auth_path: Path


@dataclass(frozen=True)
class TerminalAuthState:
    """Stored terminal auth state for current TTY."""

    email: str
    context: TerminalSessionContext


def in_tmux_context() -> bool:
    """Return True when running inside tmux."""
    return bool((os.environ.get("TMUX") or "").strip())


def _in_telec_tui_context() -> bool:
    """Return True for the trusted tc_tui tmux session created by telec."""
    return in_tmux_context() and (os.environ.get(TUI_SESSION_ENV_KEY) or "").strip() == ENV_ENABLE


def _read_bridged_tui_email() -> str | None:
    raw = os.environ.get(TUI_AUTH_EMAIL_ENV_KEY)
    if not raw:
        return None
    email = _normalize_email(raw)
    return email or None


def _read_tmux_session_name() -> str | None:
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _detect_tty() -> str | None:
    ssh_tty = (os.environ.get("SSH_TTY") or "").strip()
    if ssh_tty:
        return ssh_tty

    for fd in (0, 1, 2):
        try:
            tty = os.ttyname(fd).strip()
        except OSError:
            continue
        if tty:
            return tty
    return None


def _tty_key(tty: str) -> str:
    raw = tty.strip()
    if raw.startswith("/dev/"):
        raw = raw[5:]
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip("-")
    return normalized or "unknown-tty"


def _session_context() -> TerminalSessionContext | None:
    tty = _detect_tty()
    if not tty:
        return None
    key = _tty_key(tty)
    return TerminalSessionContext(tty=tty, key=key, auth_path=SESSION_AUTH_DIR / f"{key}.json")


def get_current_session_context() -> TerminalSessionContext | None:
    """Return current terminal session context (TTY + scoped auth file path)."""
    return _session_context()


def read_current_session_email() -> str | None:
    """Read login email for current TTY session."""
    if in_tmux_context():
        if _in_telec_tui_context():
            session_name = _read_tmux_session_name()
            if session_name and session_name == "tc_tui":
                return _read_bridged_tui_email()
        return None

    context = _session_context()
    if context is None:
        return None

    try:
        payload = context.auth_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    if not payload:
        return None

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        # Backward compatibility if file was written as plain text.
        email = _normalize_email(payload)
        return email or None

    if not isinstance(data, dict):
        return None

    raw_email = data.get("email")
    if not isinstance(raw_email, str):
        return None

    email = _normalize_email(raw_email)
    return email or None


def write_current_session_email(email: str) -> TerminalAuthState:
    """Write (overwrite) current TTY auth state with the provided email."""
    if in_tmux_context():
        raise ValueError("telec auth is unavailable inside tmux sessions.")

    normalized_email = _normalize_email(email)
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("A valid email address is required.")

    context = _session_context()
    if context is None:
        raise ValueError("No terminal session detected (TTY unavailable).")

    SESSION_AUTH_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(SESSION_AUTH_DIR, 0o700)
    except OSError:
        pass

    payload = {
        "email": normalized_email,
        "tty": context.tty,
        "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }

    tmp_path = context.auth_path.with_name(f"{context.auth_path.name}.{os.getpid()}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as tmp:
        json.dump(payload, tmp, sort_keys=True)
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
    try:
        os.chmod(tmp_path, 0o600)
    except OSError:
        pass
    os.replace(tmp_path, context.auth_path)
    try:
        os.chmod(context.auth_path, 0o600)
    except OSError:
        pass

    return TerminalAuthState(email=normalized_email, context=context)


def clear_current_session_email() -> bool:
    """Delete current TTY auth state file if it exists."""
    context = _session_context()
    if context is None:
        return False
    try:
        context.auth_path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
