"""Terminal auth state for telec login — per-TTY file with global fallback."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from teleclaude.paths import SESSION_AUTH_DIR as _PATHS_SESSION_AUTH_DIR
from teleclaude.session_identity import get_human_role

SESSION_AUTH_DIR = _PATHS_SESSION_AUTH_DIR
TUI_SESSION_ENV_KEY = "TELEC_TUI_SESSION"
TUI_CARRIED_IDENTITY_ENV_KEY = "TELEC_TUI_IDENTITY"
_NO_TTY_LABEL = "(no tty)"


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


def _detect_tty() -> str | None:
    """Detect the controlling TTY for the current process."""
    for fd in (0, 1, 2):
        try:
            return os.ttyname(fd)
        except OSError:
            continue
    return os.environ.get("SSH_TTY") or None  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state


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
    return TerminalSessionContext(tty=_NO_TTY_LABEL, key="global", auth_path=_global_auth_path())


def _detect_device_ctime(tty: str) -> float | None:
    """Return the terminal device's current allocation time, or None if unreadable."""
    try:
        return os.stat(tty).st_ctime
    except OSError:
        return None


def _normalize_email(value: str) -> str:
    return value.strip().lower()


type _AuthDocument = dict[
    str, object
]  # guard: loose-dict - parsed auth-file JSON shape varies (legacy vs. structured, with/without device_ctime)


def _read_document(path: Path) -> _AuthDocument | str | None:
    """Read and parse an auth document.

    Returns the parsed object for a structured document, the normalized
    email string for a legacy pre-structured (bare email) document, or None
    when the file is missing, empty, or not a JSON object.
    """
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
    return data


def _read_auth_file(path: Path) -> str | None:
    """Read and parse an auth file, returning the normalized email or None."""
    document = _read_document(path)
    if document is None:
        return None
    if isinstance(document, str):
        return document
    raw_email = document.get("email")
    if not isinstance(raw_email, str):
        return None
    return _normalize_email(raw_email) or None


def _read_live_document(path: Path, tty: str) -> str | None:
    """Read a per-TTY auth document, honouring it only while it is live.

    A structured document is live only while its recorded device allocation
    time still matches the device's current one — a document with no
    recorded allocation time (written before this condition existed, or
    whose device was recycled) cannot satisfy it and is treated as no
    document at all. A legacy pre-structured document (a bare email string)
    carries no device binding at all and is read unconditionally, for
    backward compatibility.
    """
    document = _read_document(path)
    if document is None:
        return None
    if isinstance(document, str):
        return document
    recorded_ctime = document.get("device_ctime")
    if not isinstance(recorded_ctime, int | float):
        return None
    current_ctime = _detect_device_ctime(tty)
    if current_ctime is None or recorded_ctime != current_ctime:
        return None
    raw_email = document.get("email")
    if not isinstance(raw_email, str):
        return None
    return _normalize_email(raw_email) or None


def read_current_session_email() -> str | None:
    """Read login email.

    Resolution order:
    1. The identity carried into a trusted TUI session (only where the TUI
       runtime marker is present — never honoured outside it)
    2. A live per-TTY auth document (device node present, allocation time matching)
    3. Global identity file — only while at most one person is registered

    A process with no controlling TTY presents no identity: nothing is
    consulted past that point.
    """
    if os.environ.get(TUI_SESSION_ENV_KEY):  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
        carried = os.environ.get(TUI_CARRIED_IDENTITY_ENV_KEY)  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
        if carried:
            return _normalize_email(carried) or None

    context = get_current_session_context()
    if context is None or context.tty == _NO_TTY_LABEL:
        return None

    email = _read_live_document(context.auth_path, context.tty)
    if email:
        return email

    from teleclaude.core.identity import (  # noqa: PLC0415 - deferred: api_client deliberately defers importing this module at load time; a module-scope import of the config-loading identity resolver would pull that cost into every CLI start
        get_identity_resolver,
    )

    if get_identity_resolver().is_multi_user:
        return None
    return _read_auth_file(_global_auth_path())


def effective_caller_role() -> str | None:
    """Return the effective human role of the current CLI caller.

    The session-recorded role when the session identity file carries one,
    otherwise the identity resolver's role for the resolved terminal login.
    """
    human_role = get_human_role()
    if human_role:
        return human_role

    from teleclaude.core.identity import (  # noqa: PLC0415 - deferred: api_client deliberately defers importing this module at load time; a module-scope import of the config-loading identity resolver would pull that cost into every CLI start
        get_identity_resolver,
    )

    return get_identity_resolver().effective_terminal_role(read_current_session_email())


def _write_auth_file(path: Path, payload: dict[str, str | float]) -> None:
    """Atomically write a JSON auth payload to *path*."""
    tmp_path = path.with_name(f"{path.stem}.{os.getpid()}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as tmp:
        json.dump(payload, tmp, sort_keys=True)
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
    try:
        os.chmod(tmp_path, 0o600)
    except OSError:
        pass
    os.replace(tmp_path, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _sweep_stale_documents() -> None:
    """Remove every per-TTY document whose device node no longer exists.

    A document whose device is still present is left untouched, including
    one belonging to another person — release is keyed on the device, not
    on who logged in last. The global fallback document is never swept.
    """
    try:
        entries = list(SESSION_AUTH_DIR.iterdir())
    except OSError:
        return
    global_path = _global_auth_path()
    for entry in entries:
        if entry == global_path or entry.suffix != ".json":
            continue
        try:
            data = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        tty = data.get("tty")
        if not isinstance(tty, str) or tty == _NO_TTY_LABEL:
            continue
        if not Path(tty).exists():
            try:
                entry.unlink()
            except OSError:
                pass


def write_current_session_email(email: str) -> TerminalAuthState:
    """Write login email to the per-TTY identity file and global identity."""
    normalized_email = _normalize_email(email)
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("A valid email address is required.")

    context = get_current_session_context()
    if context is None:
        context = TerminalSessionContext(tty=_NO_TTY_LABEL, key="global", auth_path=_global_auth_path())

    SESSION_AUTH_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(SESSION_AUTH_DIR, 0o700)
    except OSError:
        pass

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload: dict[str, str | float] = {"email": normalized_email, "tty": context.tty, "updated_at": now}
    if context.tty != _NO_TTY_LABEL:
        device_ctime = _detect_device_ctime(context.tty)
        if device_ctime is not None:
            payload["device_ctime"] = device_ctime

    _write_auth_file(context.auth_path, payload)

    # Last login always wins globally — update global identity regardless of TTY.
    global_path = _global_auth_path()
    if context.auth_path != global_path:
        _write_auth_file(global_path, payload)

    _sweep_stale_documents()

    return TerminalAuthState(email=normalized_email, context=context)


def clear_current_session_email() -> bool:
    """Delete the auth file for the current TTY (or global)."""
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
