"""Join native or admitted command execution to its session owner's fixed GitHub binding."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import psutil
from instrukt_ai_logging import get_logger
from sqlalchemy.exc import SQLAlchemyError

from teleclaude.config.machine import config
from teleclaude.config.project_models import TodoStoreBackend
from teleclaude.constants import MarkerState
from teleclaude.core.db import get_db
from teleclaude.core.operation_caller_identity import get_caller_session_id, get_relayed_caller
from teleclaude.core.project_state import resolve_owning_checkout
from teleclaude.core.roles import Role, resolve_session_role
from teleclaude.core.session_identity_facts import SessionIdentityFacts, read_session_identity_facts
from teleclaude.core.tmux_bridge._pane import get_pane_pid, get_server_pane_processes
from teleclaude.core.workflow_store.selection import selected_workflow_store_backend
from teleclaude.paths import MAIN_DB_PATH
from teleclaude.runtime.tmux_socket import own_tmux_socket_path
from teleclaude.session_identity import inspect_session_identity_marker
from teleclaude.types.github_binding import GitHubSessionBinding, GitHubWorkTarget

logger = get_logger(__name__)
_REFUSAL_LOG = "github_invocation_refused reason=%s session_id=%s"
_EXACT_SESSION_TARGET = "={name}"


class GitHubInvocationRefusal(StrEnum):
    """Reasons the managed boundary establishes no session authentication."""

    MARKER_UNRESOLVED = "marker_unresolved"
    SESSION_UNAVAILABLE = "session_unavailable"
    REMOTE_SESSION = "remote_session"
    ROLE_UNRESOLVED = "role_unresolved"
    WORK_CONTEXT_UNRESOLVED = "work_context_unresolved"
    PANE_UNAVAILABLE = "pane_unavailable"
    PROCESS_UNAVAILABLE = "process_unavailable"
    ANCESTRY_MISMATCH = "ancestry_mismatch"
    SESSION_CHANGED = "session_changed"
    EXECUTION_UNRESOLVED = "execution_unresolved"
    ACTOR_BINDING_UNAVAILABLE = "actor_binding_unavailable"
    ACTOR_BINDING_MISMATCH = "actor_binding_mismatch"


@dataclass(frozen=True)
class RefusedGitHubInvocation:
    """A managed-call refusal, with no native-human fallback disposition."""

    reason: GitHubInvocationRefusal


@dataclass(frozen=True)
class ManagedGitHubInvocation:
    """Current session facts corroborated by this process's live pane ancestry."""

    session: SessionIdentityFacts
    role: Role | None
    pane_pid: int
    pane_started_at: float


@dataclass(frozen=True)
class AdmittedGitHubInvocation:
    """Local session facts for the command/operation identity already admitted by the platform."""

    session: SessionIdentityFacts
    role: Role


@dataclass(frozen=True)
class NativeHumanGitHubInvocation:
    """Terminal execution positively observed outside every platform pane."""


@dataclass(frozen=True)
class LocalNativeGitHubInvocation:
    """Corroborated local-backend execution with no GitHub actor or target binding."""

    invocation: ManagedGitHubInvocation
    project_root: Path


@dataclass(frozen=True)
class GitHubPostingContext:
    """A corroborated invocation joined to its durable actor and exact work target."""

    invocation: ManagedGitHubInvocation | AdmittedGitHubInvocation
    binding: GitHubSessionBinding
    target: GitHubWorkTarget


def _refuse(reason: GitHubInvocationRefusal, session_id: str | None) -> RefusedGitHubInvocation:
    logger.warning(_REFUSAL_LOG, reason, session_id)
    return RefusedGitHubInvocation(reason)


def _process_ancestry() -> dict[int, float]:
    """Observe this process and its ancestors with PID-reuse-resistant identities."""
    current = psutil.Process()
    return {process.pid: process.create_time() for process in (current, *current.parents())}


def _local_session(
    session_id: str, *, allow_absent_role: bool = False
) -> tuple[SessionIdentityFacts, Role | None] | RefusedGitHubInvocation:
    """Resolve only the owning computer's open session and catalog role."""
    facts = read_session_identity_facts(str(MAIN_DB_PATH), session_id)
    if facts is None or facts.closed_at is not None or facts.deleted_at is not None:
        return _refuse(GitHubInvocationRefusal.SESSION_UNAVAILABLE, session_id)
    if facts.computer_name != config.computer.name:
        return _refuse(GitHubInvocationRefusal.REMOTE_SESSION, session_id)
    role = None
    if facts.role is None:
        if not allow_absent_role:
            return _refuse(GitHubInvocationRefusal.ROLE_UNRESOLVED, session_id)
    else:
        recorded_role = resolve_session_role(facts.role, session_id)
        if not isinstance(recorded_role, Role):
            return _refuse(GitHubInvocationRefusal.ROLE_UNRESOLVED, session_id)
        role = recorded_role
    if not facts.project_path:
        return _refuse(GitHubInvocationRefusal.WORK_CONTEXT_UNRESOLVED, session_id)
    return facts, role


async def resolve_managed_github_invocation() -> ManagedGitHubInvocation | RefusedGitHubInvocation:
    """Corroborate a marker-selected session before any platform credential lookup."""
    marker, session_id = inspect_session_identity_marker()
    if marker is not MarkerState.VALID or session_id is None:
        return _refuse(GitHubInvocationRefusal.MARKER_UNRESOLVED, session_id)
    resolved = _local_session(session_id, allow_absent_role=True)
    if isinstance(resolved, RefusedGitHubInvocation):
        return resolved
    facts, role = resolved
    socket_path = own_tmux_socket_path()
    if not facts.tmux_session_name or socket_path is None:
        return _refuse(GitHubInvocationRefusal.PANE_UNAVAILABLE, session_id)
    try:
        before = _process_ancestry()
        pane_target = _EXACT_SESSION_TARGET.format(name=facts.tmux_session_name)
        pane_pid = await get_pane_pid(pane_target, socket_path=socket_path)
        if pane_pid is None:
            return _refuse(GitHubInvocationRefusal.PANE_UNAVAILABLE, session_id)
        after = _process_ancestry()
    except psutil.Error:
        return _refuse(GitHubInvocationRefusal.PROCESS_UNAVAILABLE, session_id)
    started_at = before.get(pane_pid)
    if started_at is None or after.get(pane_pid) != started_at:
        return _refuse(GitHubInvocationRefusal.ANCESTRY_MISMATCH, session_id)
    if read_session_identity_facts(str(MAIN_DB_PATH), session_id) != facts:
        return _refuse(GitHubInvocationRefusal.SESSION_CHANGED, session_id)
    return ManagedGitHubInvocation(facts, role, pane_pid, started_at)


async def classify_native_github_invocation() -> (
    ManagedGitHubInvocation | NativeHumanGitHubInvocation | RefusedGitHubInvocation
):
    """Choose a managed boundary or corroborate native-human execution independently."""
    marker = inspect_session_identity_marker()
    if marker[0] is not MarkerState.ABSENT:
        return await resolve_managed_github_invocation()
    socket_path = own_tmux_socket_path()
    if socket_path is None:
        return _refuse(GitHubInvocationRefusal.EXECUTION_UNRESOLVED, None)
    try:
        before = _process_ancestry()
        panes = await get_server_pane_processes(socket_path)
        current = psutil.Process()
        terminals = {process.terminal() for process in (current, *current.parents())} - {None}
        if panes is None or before != _process_ancestry() or marker != inspect_session_identity_marker():
            return _refuse(GitHubInvocationRefusal.EXECUTION_UNRESOLVED, None)
    except psutil.Error:
        return _refuse(GitHubInvocationRefusal.PROCESS_UNAVAILABLE, None)
    if not terminals or any(pane.pid in before or pane.tty in terminals for pane in panes):
        return _refuse(GitHubInvocationRefusal.MARKER_UNRESOLVED, None)
    return NativeHumanGitHubInvocation()


async def resolve_native_github_posting_context() -> (
    GitHubPostingContext | LocalNativeGitHubInvocation | NativeHumanGitHubInvocation | RefusedGitHubInvocation
):
    """Resolve native execution and target/actor before the caller loads any credential."""
    invocation = await classify_native_github_invocation()
    if not isinstance(invocation, ManagedGitHubInvocation):
        return invocation
    session = invocation.session
    try:
        project_root = resolve_owning_checkout(Path(session.project_path)) if session.project_path else None
        if project_root is None:
            return _refuse(GitHubInvocationRefusal.WORK_CONTEXT_UNRESOLVED, session.session_id)
        selected = selected_workflow_store_backend(project_root)
        store = await get_db()
        binding = await store.get_github_session_binding(session.session_id)
        target = await store.get_github_native_target(session.session_id)
        if read_session_identity_facts(str(MAIN_DB_PATH), session.session_id) != session:
            return _refuse(GitHubInvocationRefusal.SESSION_CHANGED, session.session_id)
        if selected_workflow_store_backend(project_root) is not selected:
            return _refuse(GitHubInvocationRefusal.WORK_CONTEXT_UNRESOLVED, session.session_id)
        if selected is TodoStoreBackend.LOCAL:
            if binding is not None or target is not None:
                return _refuse(GitHubInvocationRefusal.ACTOR_BINDING_MISMATCH, session.session_id)
            return LocalNativeGitHubInvocation(invocation, project_root)
        context = await _bound_context(invocation)
        if selected_workflow_store_backend(project_root) is not selected:
            return _refuse(GitHubInvocationRefusal.WORK_CONTEXT_UNRESOLVED, session.session_id)
        return context
    except (SQLAlchemyError, ValueError, OSError):
        return _refuse(GitHubInvocationRefusal.WORK_CONTEXT_UNRESOLVED, session.session_id)


async def resolve_admitted_github_posting_context() -> GitHubPostingContext | RefusedGitHubInvocation:
    """Join existing admitted local command identity to authoritative bindings, without native pane proof."""
    session_id = get_caller_session_id()
    if not session_id:
        return _refuse(GitHubInvocationRefusal.EXECUTION_UNRESOLVED, None)
    # A relayed origin handle never selects a local row, even if an identifier happens to match.
    if get_relayed_caller() is not None:
        return _refuse(GitHubInvocationRefusal.REMOTE_SESSION, session_id)
    resolved = _local_session(session_id)
    if isinstance(resolved, RefusedGitHubInvocation):
        return resolved
    session, role = resolved
    if role is None:
        return _refuse(GitHubInvocationRefusal.ROLE_UNRESOLVED, session_id)
    context = await _bound_context(AdmittedGitHubInvocation(session, role))
    if get_caller_session_id() != session_id or get_relayed_caller() is not None:
        return _refuse(GitHubInvocationRefusal.SESSION_CHANGED, session_id)
    return context


async def _bound_context(
    invocation: ManagedGitHubInvocation | AdmittedGitHubInvocation,
) -> GitHubPostingContext | RefusedGitHubInvocation:
    """Read fixed actor and work scope once from their existing session owner, then recheck the source row."""
    session = invocation.session
    if invocation.role is None:
        return _refuse(GitHubInvocationRefusal.ROLE_UNRESOLVED, session.session_id)
    try:
        store = await get_db()
        binding = await store.get_github_session_binding(session.session_id)
        target = await store.get_github_native_target(session.session_id)
        if binding is None or target is None:
            return _refuse(GitHubInvocationRefusal.ACTOR_BINDING_UNAVAILABLE, session.session_id)
        project_root = resolve_owning_checkout(Path(session.project_path)) if session.project_path else None
        if (
            binding.session_id != session.session_id
            or binding.role is not invocation.role.name
            or session.working_slug != target.work_item
            or project_root is None
            or resolve_owning_checkout(target.project_path) != project_root
        ):
            return _refuse(GitHubInvocationRefusal.ACTOR_BINDING_MISMATCH, session.session_id)
    except (SQLAlchemyError, ValueError, OSError):
        return _refuse(GitHubInvocationRefusal.ACTOR_BINDING_UNAVAILABLE, session.session_id)
    if read_session_identity_facts(str(MAIN_DB_PATH), session.session_id) != session:
        return _refuse(GitHubInvocationRefusal.SESSION_CHANGED, session.session_id)
    return GitHubPostingContext(invocation, binding, target)
