"""Terminal auth state for telec login — one document per terminal, no machine-global record."""

from __future__ import annotations

import json
import os
import sys
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

import psutil
from instrukt_ai_logging import get_logger

from teleclaude.agent_registry import native_session_id_env_names
from teleclaude.caller_identity import (
    CliCaller,
    NoIdentityCliCaller,
    Person,
    PersonCliCaller,
    Platform,
    ProjectPath,
    RoleResolver,
    RoleTarget,
    SessionAct,
    SessionOf,
    human_principal_for_email,
    identity_for_session,
    is_desk_visitor,
    person_entry_for_email,
    session_act_exception,
)
from teleclaude.cli import CommandScope
from teleclaude.cli.telec.surface_types import admits_any_caller
from teleclaude.config.loader import load_global_config
from teleclaude.config.machine import config
from teleclaude.constants import (
    HUMAN_ROLE_CUSTOMER,
    LOCAL_COMPUTER,
    LOGIN_REQUIRED_DETAIL,
    SYSTEM_DAEMON_PRINCIPAL,
    TUI_SESSION_ENV_KEY,
    MarkerState,
)
from teleclaude.core.roles import Capability, Role, UnknownRole, allows, is_focused_role, resolve_session_role
from teleclaude.core.session_identity_facts import (
    SessionIdentityFacts,
    read_live_session_id_by_native,
    read_session_identity_facts,
)
from teleclaude.paths import MAIN_DB_PATH, invocation_cwd
from teleclaude.paths import SESSION_AUTH_DIR as _PATHS_SESSION_AUTH_DIR
from teleclaude.session_identity import inspect_session_identity_marker
from teleclaude.types.creation_record import EntryPoint

logger = get_logger(__name__)

SESSION_AUTH_DIR = _PATHS_SESSION_AUTH_DIR
TUI_CARRIED_IDENTITY_ENV_KEY = "TELEC_TUI_IDENTITY"
_OUTSIDE_AGENT_RESOLVED_EVENT = "outside_agent_resolved_to_headless_session"
_NO_TERMINAL_ERROR = "No terminal detected: telec auth login must run from an interactive terminal."
_DEVICE_ALLOCATION_KEY = "device_allocation"
_DARWIN_PLATFORM = "darwin"
_INODE_ALLOCATION_PREFIX = "ino:"
_CTIME_ALLOCATION_PREFIX = "ctime:"


class ComputerTargetDisposition(StrEnum):
    """Identity-owned classification for an optional explicit computer target."""

    LOCAL = "local"
    REMOTE = "remote"


def classify_computer_target(target_computer: str | None) -> ComputerTargetDisposition:
    """Classify an explicit target against the local sentinel and this computer's configured name."""
    if not target_computer or target_computer == LOCAL_COMPUTER:
        return ComputerTargetDisposition.LOCAL
    if target_computer == config.computer.name:
        return ComputerTargetDisposition.LOCAL
    return ComputerTargetDisposition.REMOTE


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


@dataclass(frozen=True)
class ResolvedCliIdentity:
    """Identity facts resolved once for a local CLI invocation."""

    caller: CliCaller
    principal: str | None
    role: str | None
    session_id: str | None
    in_session: bool
    initiator_session_id: str | None = None
    job: str | None = None
    working_slug: str | None = None
    company: str | None = None
    session_facts: SessionIdentityFacts | None = None
    entry_point: str | None = None


@dataclass(frozen=True)
class CliClearance:
    """One command's non-exiting caller clearance decision."""

    identity: ResolvedCliIdentity | None
    refusal: str | None


class CommandAuthDeclaration(Protocol):
    """The auth declaration fields the identity gate consumes."""

    @property
    def caller_independent(self) -> bool: ...

    @property
    def machine_account(self) -> bool: ...

    @property
    def capability(self) -> Capability | None: ...

    @property
    def scope(self) -> CommandScope: ...

    def allows(self, role: Role | UnknownRole | None, human_role: str | None) -> bool: ...


_INVOCATION_IDENTITY_NAME = "telec_cli_invocation_identity"
_INVOCATION_IDENTITY: ContextVar[ResolvedCliIdentity | None] = ContextVar(
    _INVOCATION_IDENTITY_NAME,
    default=None,
)
_INVOCATION_COMMAND_NAME = "telec_cli_invocation_command"
_INVOCATION_COMMAND: ContextVar[str | None] = ContextVar(_INVOCATION_COMMAND_NAME, default=None)
SELF_SESSION_TARGET = "self"
_UNAUTHORIZED_ROLE = "unauthorized"
_SESSION_END_PATH = "sessions end"
_SESSION_RESTART_PATH = "sessions restart"
_SESSION_SHOW_PATH = "sessions show"
_CALLER_INDEPENDENT_COMMAND_REFUSAL = "Unknown command path or missing command authorization."
_DESK_COMMAND_REFUSAL_TEMPLATE = "permission denied — {command_path} is not available at a help desk"
_PERMISSION_REFUSAL_TEMPLATE = "permission denied — role '{role}' is not permitted to call {command_path}"
_WORKER_REPORTING_PATH_TEMPLATE = "{refusal}. A focused session reports through its own output and artifacts, which the session that dispatched it routes."


def _permission_refusal(identity: ResolvedCliIdentity, role: str, command_path: str) -> str:
    """The not-permitted refusal; a focused session's also names where its result belongs."""
    refusal = _PERMISSION_REFUSAL_TEMPLATE.format(role=role, command_path=command_path)
    if is_focused_role(identity.role):
        return _WORKER_REPORTING_PATH_TEMPLATE.format(refusal=refusal)
    return refusal


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
    """Resolve a terminal email without consulting the configuration aggregate."""
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
    people = load_global_config().people
    return people[0].email.strip().lower() if len(people) == 1 else None


def _no_identity(in_session: bool) -> ResolvedCliIdentity:
    return ResolvedCliIdentity(
        caller=NoIdentityCliCaller(),
        principal=None,
        role=None,
        session_id=None,
        in_session=in_session,
        entry_point=_entry_point_for_caller(in_session=in_session),
    )


def _entry_point_for_caller(*, in_session: bool) -> str:
    """Name the client door that resolved this identity."""
    if in_session:
        return EntryPoint.AGENT.value
    if os.environ.get(TUI_SESSION_ENV_KEY):  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
        return EntryPoint.TUI.value
    return EntryPoint.CLI.value


def resolve_cli_identity() -> ResolvedCliIdentity:
    """Return the gate resolution for this invocation or resolve an identity for an edge caller."""
    invocation_identity = _INVOCATION_IDENTITY.get()
    if invocation_identity is not None:
        return invocation_identity

    marker_state, session_id = inspect_session_identity_marker()
    if marker_state is MarkerState.ABSENT:
        outside_agent_session_id = _outside_agent_session_id()
        if outside_agent_session_id is not None:
            return _resolve_session_identity(outside_agent_session_id)
        email = read_current_session_email()
        person = person_entry_for_email(email) if email else None
        if person is None:
            return _no_identity(False)
        caller = PersonCliCaller(
            email=person.email,
            person_slug=person.slug,
            human_role=person.role,
        )
        return ResolvedCliIdentity(
            caller=caller,
            principal=human_principal_for_email(person.email),
            role=None,
            session_id=None,
            in_session=False,
            entry_point=_entry_point_for_caller(in_session=False),
        )
    if marker_state is MarkerState.INVALID:
        return _no_identity(True)

    return _resolve_session_identity(session_id)


def _outside_agent_session_id() -> str | None:
    """Return the live session an agent running outside the platform names through its runtime.

    A runtime exports its own native session id to the tool processes it spawns,
    and the agent's first hook already recorded that id on a session. A call
    carrying no session marker and not launched from the TUI resolves to that
    session when one is live; any other call is a person's terminal and resolves
    from the terminal login.
    """
    if os.environ.get(TUI_SESSION_ENV_KEY):  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
        return None
    for env_name in native_session_id_env_names():
        native_session_id = os.environ.get(env_name)  # fmt: skip  # guard: direct-env-read - allowed: ambient host or terminal state
        if native_session_id is None or not native_session_id.strip():
            continue
        live_session_id = read_live_session_id_by_native(str(MAIN_DB_PATH), native_session_id.strip())
        if live_session_id is not None:
            logger.info(_OUTSIDE_AGENT_RESOLVED_EVENT, session_id=live_session_id, env_name=env_name)
            return live_session_id
    return None


def _resolve_session_identity(session_id: str | None) -> ResolvedCliIdentity:
    """Resolve the identity of an admitted session, or an unresolved in-session caller."""
    facts = _admitted_session_record(_load_session_record(session_id))
    if facts is None:
        return _no_identity(True)
    resolved = identity_for_session(facts)
    return ResolvedCliIdentity(
        caller=resolved.caller,
        principal=resolved.principal,
        role=resolved.role,
        session_id=facts.session_id,
        in_session=True,
        initiator_session_id=facts.initiator_session_id,
        job=facts.job,
        working_slug=facts.working_slug,
        company=facts.company,
        session_facts=facts,
        entry_point=_entry_point_for_caller(in_session=True),
    )


def resolve_cli_caller() -> CliCaller:
    """Resolve the local caller from the gate's decision or current edge identity."""
    return resolve_cli_identity().caller


def no_identity_refusal(identity: ResolvedCliIdentity) -> str:
    """Return the refusal detail for an unresolved session or terminal caller."""
    if identity.in_session:
        return "The current session carries no usable identity."
    return f"{LOGIN_REQUIRED_DETAIL}. Run: telec auth login <email>"


def _fallback_role_target(
    auth: CommandAuthDeclaration,
    identity: ResolvedCliIdentity,
    target_session_id: str | None,
) -> RoleTarget:
    """Fail closed when a target-scoped caller did not supply the object."""
    if auth.scope is CommandScope.PLATFORM:
        return Platform()
    if auth.scope is CommandScope.TARGET_SESSION:
        resolved_target = identity.session_id if target_session_id == SELF_SESSION_TARGET else target_session_id
        if resolved_target is None:
            return ProjectPath(invocation_cwd())
        facts = _load_session_record(resolved_target)
        if facts is not None and facts.project_path is not None:
            return SessionOf(Path(facts.project_path))
        return Platform()
    if auth.scope is CommandScope.CALLER_PERSON:
        person_slug = identity.caller.person_slug
        return Person(person_slug) if person_slug else Platform()
    if auth.scope is not CommandScope.INVOCATION:
        return Platform()
    return ProjectPath(invocation_cwd())


def cli_clearance(
    command_path: str,
    identity: ResolvedCliIdentity | None,
    target_session_id: str | None = None,
    auth: CommandAuthDeclaration | None = None,
    *,
    role_target: RoleTarget | None = None,
    target_computer: str | None = None,
    direct_conversation: bool = False,
    desk_command: bool = False,
) -> CliClearance:
    """Decide one command's clearance without printing or exiting.

    An anonymous help-desk visitor is admitted only to commands the surface
    declares safe for a desk (``desk_command``), caller-independent ones
    included; every other caller is decided as before. A caller outside any session is admitted to a
    command the machine's own account operates (``machine_account``) on this computer, logged in or
    not; a session, valid or invalid, never takes that path.
    """
    if auth is None:
        return CliClearance(identity=identity, refusal=_CALLER_INDEPENDENT_COMMAND_REFUSAL)
    if admits_any_caller(auth.caller_independent, desk_command):
        return CliClearance(identity=None, refusal=None)
    remote_target = classify_computer_target(target_computer) is ComputerTargetDisposition.REMOTE
    relayed_request = remote_target and not direct_conversation
    if identity is not None and is_desk_visitor(identity.caller) and not desk_command and not relayed_request:
        return CliClearance(identity=identity, refusal=_DESK_COMMAND_REFUSAL_TEMPLATE.format(command_path=command_path))
    if auth.caller_independent:
        return CliClearance(identity=None, refusal=None)
    if identity is None:
        identity = _no_identity(False)
    if auth.machine_account and not identity.in_session and not remote_target:
        return CliClearance(identity=identity, refusal=None)
    if isinstance(identity.caller, NoIdentityCliCaller) or (relayed_request and not identity.principal):
        return CliClearance(identity=identity, refusal=no_identity_refusal(identity))

    if relayed_request:
        # The holding computer never receives a role, so a focused session's session acts are refused here, before relay.
        if is_focused_role(identity.role) and auth.capability is Capability.PEER_TALK:
            role = identity.role or _UNAUTHORIZED_ROLE
            return CliClearance(identity=identity, refusal=_permission_refusal(identity, role, command_path))
        return CliClearance(identity=identity, refusal=None)

    if identity.principal == SYSTEM_DAEMON_PRINCIPAL and identity.role is None:
        return CliClearance(identity=identity, refusal=None)

    action = {
        _SESSION_END_PATH: SessionAct.END,
        _SESSION_RESTART_PATH: SessionAct.RESTART,
        _SESSION_SHOW_PATH: SessionAct.SHOW,
    }.get(command_path)
    if action is not None:
        # Showing a session without naming one shows the caller's own.
        names_self = target_session_id == SELF_SESSION_TARGET or (
            action is SessionAct.SHOW and target_session_id is None
        )
        action_session_target = identity.session_id if names_self else target_session_id
        exception = session_act_exception(
            action,
            identity.session_id,
            identity.initiator_session_id,
            identity.role,
            action_session_target,
        )
        if exception is True:
            return CliClearance(identity=identity, refusal=None)
        if exception is False:
            role = identity.role or identity.caller.human_role or "unauthorized"
            return CliClearance(
                identity=identity,
                refusal=_permission_refusal(identity, role, command_path),
            )

    agent_role = resolve_session_role(identity.role, identity.session_id)
    if auth.scope is CommandScope.NAMED_TRUSTED_DIRECTORY and role_target is None:
        person_caller = isinstance(identity.caller, PersonCliCaller)
        reaches_capability = (
            isinstance(agent_role, Role) and auth.capability is not None and allows(agent_role, auth.capability)
        )
        if (person_caller and agent_role is None) or reaches_capability:
            return CliClearance(identity=identity, refusal=None)
        role = identity.role or _UNAUTHORIZED_ROLE
        return CliClearance(
            identity=identity,
            refusal=_permission_refusal(identity, role, command_path),
        )

    resolved_role_target = role_target or _fallback_role_target(auth, identity, target_session_id)
    if remote_target:
        # Only a direct conversation reaches here: it stays on the caller's computer at platform scope.
        resolved_role_target = Platform()
    person_role = (
        RoleResolver().role_for(identity.caller, resolved_role_target)
        if isinstance(identity.caller, PersonCliCaller)
        else None
    )
    if auth.allows(agent_role, person_role):
        return CliClearance(identity=identity, refusal=None)
    if (
        isinstance(agent_role, Role)
        and auth.capability is not None
        and allows(agent_role, auth.capability)
        and isinstance(identity.caller, PersonCliCaller)
    ):
        role = person_role or HUMAN_ROLE_CUSTOMER
    else:
        role = identity.role or person_role or _UNAUTHORIZED_ROLE
    return CliClearance(
        identity=identity,
        refusal=_permission_refusal(identity, role, command_path),
    )


def require_cli_clearance(
    command_path: str,
    target_session_id: str | None = None,
    auth: CommandAuthDeclaration | None = None,
    *,
    role_target: RoleTarget | None = None,
    target_computer: str | None = None,
    direct_conversation: bool = False,
    desk_command: bool = False,
) -> ResolvedCliIdentity | None:
    """Resolve and enforce one local CLI command's declared authorization."""
    clearance = cli_clearance(
        command_path,
        resolve_cli_identity(),
        target_session_id,
        auth,
        role_target=role_target,
        target_computer=target_computer,
        direct_conversation=direct_conversation,
        desk_command=desk_command,
    )
    if clearance.refusal is not None:
        print(f"Error: {clearance.refusal}", file=sys.stderr)
        raise SystemExit(1)
    _INVOCATION_IDENTITY.set(clearance.identity)
    _INVOCATION_COMMAND.set(command_path)
    return clearance.identity


def resolve_cleared_command() -> str | None:
    """The command path this invocation's gate cleared the caller for, if the gate ran."""
    return _INVOCATION_COMMAND.get()


def _load_session_record(session_id: str | None) -> SessionIdentityFacts | None:
    if session_id is None:
        return None
    return read_session_identity_facts(str(MAIN_DB_PATH), session_id)


def _admitted_session_record(facts: SessionIdentityFacts | None) -> SessionIdentityFacts | None:
    if facts is None or facts.closed_at is not None:
        return None
    return facts


def effective_caller_role() -> str | None:
    """Return the current CLI caller's human role, if they have one."""
    return resolve_cli_identity().caller.human_role


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
