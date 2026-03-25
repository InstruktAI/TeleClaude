"""Terminal auth state for telec login — per-TTY file with global fallback."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

SESSION_AUTH_DIR = Path("~/.local/state/telec/session-auth").expanduser()
TUI_SESSION_ENV_KEY = "TELEC_TUI_SESSION"


@dataclass(frozen=True)
class TerminalSessionContext:
    """Per-TTY auth context pointing at the identity file for this terminal."""

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


def _detect_tty() -> str | None:
    """Detect the controlling TTY for the current process."""
    for fd in (0, 1, 2):
        try:
            return os.ttyname(fd)
        except OSError:
            continue
    return os.environ.get("SSH_TTY") or None


def _tty_key(tty: str) -> str:
    """Convert a TTY path to a filesystem-safe key.

    ``/dev/ttys003`` becomes ``ttys003``.
    """
    return tty.rsplit("/", 1)[-1]


def _global_auth_path() -> Path:
    return SESSION_AUTH_DIR / "global_identity.json"


def get_current_session_context() -> TerminalSessionContext | None:
    """Return a context for the current terminal.

    Per-TTY when a TTY is detectable, global fallback otherwise.
    """
    tty = _detect_tty()
    if tty:
        key = _tty_key(tty)
        return TerminalSessionContext(tty=tty, key=key, auth_path=SESSION_AUTH_DIR / f"{key}.json")
    return TerminalSessionContext(tty="(no tty)", key="global", auth_path=_global_auth_path())


def _normalize_email(value: str) -> str:
    return value.strip().lower()


def _read_auth_file(path: Path) -> str | None:
    """Read and parse an auth file, returning the normalized email or None."""
    try:
        payload = path.read_text(encoding="utf-8").strip()
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


def read_current_session_email() -> str | None:
    """Read login email.

    Resolution order:
    1. Per-TTY auth file (when TTY detectable)
    2. Global identity file (fallback)
    """
    tty = _detect_tty()
    if tty:
        key = _tty_key(tty)
        email = _read_auth_file(SESSION_AUTH_DIR / f"{key}.json")
        if email:
            return email

    return _read_auth_file(_global_auth_path())


def write_current_session_email(email: str) -> TerminalAuthState:
    """Write login email to the per-TTY identity file."""
    normalized_email = _normalize_email(email)
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("A valid email address is required.")

    tty = _detect_tty()
    if tty:
        key = _tty_key(tty)
        auth_path = SESSION_AUTH_DIR / f"{key}.json"
    else:
        key = "global"
        tty = "(no tty)"
        auth_path = _global_auth_path()

    SESSION_AUTH_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(SESSION_AUTH_DIR, 0o700)
    except OSError:
        pass

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload = {"email": normalized_email, "tty": tty, "updated_at": now}

    tmp_path = auth_path.with_name(f"{auth_path.stem}.{os.getpid()}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as tmp:
        json.dump(payload, tmp, sort_keys=True)
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
    try:
        os.chmod(tmp_path, 0o600)
    except OSError:
        pass
    os.replace(tmp_path, auth_path)
    try:
        os.chmod(auth_path, 0o600)
    except OSError:
        pass

    context = TerminalSessionContext(tty=tty, key=key, auth_path=auth_path)
    return TerminalAuthState(email=normalized_email, context=context)


def clear_current_session_email() -> bool:
    """Delete the auth file for the current TTY (or global)."""
    tty = _detect_tty()
    if tty:
        key = _tty_key(tty)
        auth_path = SESSION_AUTH_DIR / f"{key}.json"
    else:
        auth_path = _global_auth_path()
    try:
        auth_path.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
