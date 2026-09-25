"""Terminal auth state for telec login — one document per terminal, no machine-global record."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import psutil

from teleclaude.config import config
from teleclaude.constants import MarkerState
from teleclaude.paths import MAIN_DB_PATH
from teleclaude.paths import SESSION_AUTH_DIR as _PATHS_SESSION_AUTH_DIR
from teleclaude.session_identity import inspect_session_identity_marker

SESSION_AUTH_DIR = _PATHS_SESSION_AUTH_DIR
TUI_SESSION_ENV_KEY = "TELEC_TUI_SESSION"
TUI_CARRIED_IDENTITY_ENV_KEY = "TELEC_TUI_IDENTITY"
_NO_TERMINAL_ERROR = "No terminal detected: telec auth login must run from an interactive terminal."
_DEVICE_ALLOCATION_KEY = "device_allocation"
_DARWIN_PLATFORM = "darwin"
_INODE_ALLOCATION_PREFIX = "ino:"
_CTIME_ALLOCATION_PREFIX = "ctime:"

if TYPE_CHECKING:
    from teleclaude.core.identity import CliCaller
    from teleclaude.core.models import Session


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


def _detect_ancestor_tty() -> str | None:
    """Return the terminal of the nearest ancestor process that has one.

    An agent CLI started from a terminal runs its tool shells detached from that
    terminal, yet they act for the person who launched it. Service-manager
    processes outside terminal-bearing sessions have no terminal ancestor. A
    daemon-spawned tmux session does have a pane terminal ancestor; the session
    identity marker prevents that terminal login from becoming its identity.
    """
    try:
        for ancestor in psutil.Process().parents():
            terminal: str | None = ancestor.terminal()
            if terminal:
                return terminal
    except psutil.Error:
        return None
    return None


def _detect_tty() -> str | None:
    """Detect the controlling TTY for the current process, else its nearest terminal-bearing ancestor's."""
    for fd in (0, 1, 2):
        try:
            return os.ttyname(fd)
        except OSError:
            continue
    ssh_tty = os.environ.get("SSH_TTY")  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
    if ssh_tty:
        return ssh_tty
    return _detect_ancestor_tty()


def _tty_key(tty: str) -> str:
    """Convert a TTY path to a filesystem-safe key.

    ``/dev/ttys003`` becomes ``ttys003``.
    """
    return tty.rsplit("/", 1)[-1]


def get_current_session_context() -> TerminalSessionContext | None:
    """Return the auth context for the current terminal, or None when no terminal is detectable."""
    tty = _detect_tty()
    if not tty:
        return None
    key = _tty_key(tty)
    return TerminalSessionContext(tty=tty, key=key, auth_path=SESSION_AUTH_DIR / f"{key}.json")


def _detect_device_allocation(tty: str) -> str | None:
    """Return a token identifying the terminal device's current allocation, or None if unreadable.

    macOS devfs moves a pty's ctime on every write but issues a fresh inode each
    time the pty is allocated, so the inode is the allocation discriminator there.
    Linux devpts derives the inode from the pty index (stable across reuse) and
    leaves ctime untouched by terminal I/O, so ctime is the discriminator there.
    """
    try:
        stat = os.stat(tty)
    except OSError:
        return None
    if sys.platform == _DARWIN_PLATFORM:
        return f"{_INODE_ALLOCATION_PREFIX}{stat.st_ino}"
    return f"{_CTIME_ALLOCATION_PREFIX}{stat.st_ctime}"


def _normalize_email(value: str) -> str:
    return value.strip().lower()


type _AuthDocument = dict[
    str, object
]  # guard: loose-dict - parsed auth-file JSON shape varies (legacy vs. structured, with/without device_allocation)


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


def _read_live_document(path: Path, tty: str) -> str | None:
    """Read a per-TTY auth document, honouring it only while it is live.

    A structured document is live only while its recorded device allocation
    time still matches the device's current one — a document with no
    recorded allocation token (written before this condition existed, or
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
    recorded_allocation = document.get(_DEVICE_ALLOCATION_KEY)
    if not isinstance(recorded_allocation, str):
        return None
    current_allocation = _detect_device_allocation(tty)
    if current_allocation is None or recorded_allocation != current_allocation:
        return None
    raw_email = document.get("email")
    if not isinstance(raw_email, str):
        return None
    return _normalize_email(raw_email) or None


def read_current_session_email() -> str | None:
    """Read login email.

    A present session identity document, valid or not, suppresses terminal
    login before any other source is consulted. With no such document, resolve
    in order:
    1. Identity carried into a trusted TUI session (only where the TUI runtime
       marker is present — never honoured outside it)
    2. A live auth document for the process's terminal — its own, else its
       nearest terminal-bearing ancestor's (device node present, allocation
       token matching)
    3. The sole registered person — only while exactly one person is registered

    A process with no terminal of its own or in its ancestry presents no
    identity: nothing is consulted past that point.
    """
    marker_state, _session_id = inspect_session_identity_marker()
    if marker_state is not MarkerState.ABSENT:
        return None

    if os.environ.get(TUI_SESSION_ENV_KEY):  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
        carried = os.environ.get(TUI_CARRIED_IDENTITY_ENV_KEY)  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
        if carried:
            return _normalize_email(carried) or None

    context = get_current_session_context()
    if context is None:
        return None

    email = _read_live_document(context.auth_path, context.tty)
    if email:
        return email

    from teleclaude.core.identity import (  # noqa: PLC0415 - deferred: api_client deliberately defers importing this module at load time; a module-scope import of the config-loading identity resolver would pull that cost into every CLI start
        get_identity_resolver,
    )

    return get_identity_resolver().sole_person_email


def resolve_cli_caller() -> CliCaller:
    """Resolve the local caller from its carried principal or edge identity."""
    from teleclaude.core.identity import (  # noqa: PLC0415 - keep config-loading identity code out of every CLI start
        NoIdentityCliCaller,
        PersonCliCaller,
        caller_for_session,
        get_identity_resolver,
    )

    marker_state, session_id = inspect_session_identity_marker()
    if marker_state is MarkerState.ABSENT:
        email = read_current_session_email()
        if not email:
            return NoIdentityCliCaller()
        identity_resolver = get_identity_resolver()
        person = identity_resolver.resolve_by_email(email)
        if not person.person_email:
            return NoIdentityCliCaller()
        return PersonCliCaller(
            email=person.person_email,
            person_slug=person.person_slug,
            human_role=person.person_role,
        )
    if marker_state is MarkerState.INVALID:
        return NoIdentityCliCaller()

    session = _admitted_session_record(_load_session_record(session_id))
    if session is None:
        return NoIdentityCliCaller()
    return caller_for_session(session)


def resolve_cli_system_role() -> str | None:
    """Resolve the current session's system role from its admitted record."""
    marker_state, session_id = inspect_session_identity_marker()
    if marker_state is not MarkerState.VALID:
        return None
    session = _admitted_session_record(_load_session_record(session_id))
    if session is None or session.system_role is None:
        return None
    return session.system_role.strip().lower()


def _load_session_record(session_id: str | None) -> Session | None:
    if session_id is None:
        return None
    from teleclaude.core import db  # noqa: PLC0415 - deferred: core.db reaches this CLI module during startup

    return db.get_session_identity_sync(str(MAIN_DB_PATH), session_id)


def _admitted_session_record(session: Session | None) -> Session | None:
    if session is None or session.closed_at is not None:
        return None
    if session.computer_name != config.computer.name:
        return None
    return session


def effective_caller_role() -> str | None:
    """Return the current CLI caller's human role, if it has a person identity."""
    return resolve_cli_caller().human_role


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
    on who logged in last.
    """
    try:
        entries = list(SESSION_AUTH_DIR.iterdir())
    except OSError:
        return
    for entry in entries:
        if entry.suffix != ".json":
            continue
        try:
            data = json.loads(entry.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        tty = data.get("tty")
        if not isinstance(tty, str):
            continue
        if not Path(tty).exists():
            try:
                entry.unlink()
            except OSError:
                pass


def write_current_session_email(email: str) -> TerminalAuthState:
    """Write login email to the current terminal's identity document."""
    normalized_email = _normalize_email(email)
    if not normalized_email or "@" not in normalized_email:
        raise ValueError("A valid email address is required.")

    context = get_current_session_context()
    if context is None:
        raise ValueError(_NO_TERMINAL_ERROR)

    SESSION_AUTH_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(SESSION_AUTH_DIR, 0o700)
    except OSError:
        pass

    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload: dict[str, str | float] = {"email": normalized_email, "tty": context.tty, "updated_at": now}
    device_allocation = _detect_device_allocation(context.tty)
    if device_allocation is not None:
        payload[_DEVICE_ALLOCATION_KEY] = device_allocation

    _write_auth_file(context.auth_path, payload)

    _sweep_stale_documents()

    return TerminalAuthState(email=normalized_email, context=context)


def clear_current_session_email() -> bool:
    """Delete the auth file for the current terminal."""
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
