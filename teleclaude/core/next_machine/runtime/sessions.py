"""Live session lookup helpers shared across next-machine state machines."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from teleclaude.config.project_models import TodoStoreBackend
from teleclaude.constants import WORKTREE_DIR
from teleclaude.core.agent_status_projection import read_session_agent_status
from teleclaude.core.db import Db
from teleclaude.core.models import Session
from teleclaude.core.next_machine.lanes import DRIVER_ROLES, LifecycleProcedure
from teleclaude.core.next_machine.runtime.driver_starts import is_starting
from teleclaude.core.project_state import resolve_project_state_root
from teleclaude.core.session_status import AgentStatusValue, SessionLifecycleStatus
from teleclaude.core.workflow_store.selection import selected_workflow_store_backend
from teleclaude.types.todos import ACTIVE_RUNNER_STATE_KEY

if TYPE_CHECKING:
    from teleclaude.core.workflow_store.store import WorkflowStore

CommandValues = str | tuple[str, ...]
PREPARE_LIFECYCLE_COMMANDS: tuple[str, ...] = (
    LifecycleProcedure.PREPARE.value,
    LifecycleProcedure.INTAKE.value,
    LifecycleProcedure.ARCHITECTURE.value,
    LifecycleProcedure.DIAGNOSE.value,
    LifecycleProcedure.PLAN_DRAFT.value,
    LifecycleProcedure.REVIEW_ARCHITECTURE.value,
    LifecycleProcedure.REVIEW_PLAN.value,
    LifecycleProcedure.DRIFT_ANALYZE.value,
)


def _normalize_commands(command_values: CommandValues) -> tuple[str, ...]:
    """Return a uniform tuple of canonical command values."""
    values = (command_values,) if isinstance(command_values, str) else command_values
    return tuple(value.lstrip("/") for value in values)


def _matches_command(command: str | None, command_values: CommandValues) -> bool:
    """Return whether a recorded command matches one of the requested values."""
    return command in _normalize_commands(command_values)


def _expected_subdir(slug: str, subdir_override: str | None) -> str | None:
    """Resolve the canonical subdir used to scope live-session ownership.

    ``subdir_override=""`` and ``subdir_override=None`` both mean "session has
    no subdir". The API stores ``subfolder or None``, so an empty override must
    normalize to ``None`` to match. A non-empty override is returned as-is. A
    missing override defaults to the per-slug worktree path.
    """
    if subdir_override is not None:
        return subdir_override or None
    return f"{WORKTREE_DIR}/{slug}"


async def find_live_session_for_slug(
    db: Db,
    slug: str,
    command_values: CommandValues,
    subdir_override: str | None = None,
) -> str | None:
    """Return the newest live session id for a slug and command-family prefix."""
    expected_subdir = _expected_subdir(slug, subdir_override)
    sessions = await db.list_sessions(include_closed=False)
    for session in sessions:
        if session.subdir != expected_subdir:
            continue
        if session.working_slug == slug and _matches_command(session.command, command_values):
            return session.session_id
    return None


async def find_live_session_with_status_for_slug(
    db: Db,
    slug: str,
    command_values: CommandValues,
    subdir_override: str | None = None,
) -> tuple[str | None, str]:
    """Return the newest live session id plus computed agent status for a slug."""
    expected_subdir = _expected_subdir(slug, subdir_override)
    sessions = await db.list_sessions(include_closed=False)
    for session in sessions:
        if session.subdir != expected_subdir:
            continue
        if session.working_slug != slug or not _matches_command(session.command, command_values):
            continue
        return session.session_id, read_session_agent_status(session).value
    return None, AgentStatusValue.UNKNOWN.value


async def find_all_live_sessions_for_slug(
    db: Db,
    slug: str,
    subdir_override: str | None = None,
    project_path: str | Path | None = None,
) -> list[str]:
    """Return live session ids for a slug, optionally scoped to its project."""
    expected_subdir = _expected_subdir(slug, subdir_override)
    project_root = Path(project_path).resolve() if project_path is not None else None
    sessions = await db.list_sessions(include_closed=False)
    return [
        session.session_id
        for session in sessions
        if session.subdir == expected_subdir
        and (project_root is None or _same_project_root(session.project_path, project_root))
    ]


async def is_live_session_id(db: Db, session_id: str) -> bool:
    """Return whether a concrete TeleClaude session id still names a live session."""
    session = await db.get_session(session_id)
    if session is None:
        return False
    if session.closed_at is not None:
        return False
    return session.lifecycle_status != "closed"


class OwnSessionAnswer(StrEnum):
    """What one computer says about a session id it is asked about, for one todo."""

    HELD = "held"
    ENDED = "ended"
    NOT_OWN = "not_own"


def is_github_backed(project_path: str | Path) -> bool:
    """Return whether the project's workflow records live in the GitHub store shared across computers."""
    return selected_workflow_store_backend(resolve_project_state_root(project_path)) is TodoStoreBackend.GITHUB


async def own_session_answer(db: Db, project_path: str | Path, slug: str, session_id: str) -> OwnSessionAnswer:
    """Answer, for this computer only, whether ``session_id`` drives ``slug`` in this project.

    Each computer's registry is authoritative for the sessions it ran, and its retained records
    (closed, closing and deleted sessions stay) let it say "mine and ended" as well as "mine and held":

    - ``HELD`` — a start of that session for this todo is inside this computer's admission section, or
      the session is open, not closing, carries a lifecycle driver role and has ``slug`` as its working
      slug in this project;
    - ``ENDED`` — this computer holds a record of that session and it neither holds nor is starting
      (closed, closing, deleted, or open without driving this todo);
    - ``NOT_OWN`` — this computer has no record of it and no start of it.

    Judging the session as the driver of this todo, not as merely open, is what lets an in-place start
    that gave up, whose caller stays open without driving the todo, be judged ended.
    """
    if is_starting(project_path, slug, session_id):
        return OwnSessionAnswer.HELD
    session = await db.get_session(session_id)
    if session is None:
        return OwnSessionAnswer.NOT_OWN
    drives_slug = (
        session.closed_at is None
        and session.deleted_at is None
        and session.lifecycle_status not in {SessionLifecycleStatus.CLOSED, SessionLifecycleStatus.CLOSING}
        and session.role in DRIVER_ROLES
        and session.working_slug == slug
        and _same_project_root(session.project_path, Path(project_path).resolve())
    )
    return OwnSessionAnswer.HELD if drives_slug else OwnSessionAnswer.ENDED


async def claim_is_held(db: Db, project_path: str | Path, slug: str, session_id: str) -> bool:
    """Return whether the claim naming ``session_id`` on ``slug`` still holds the todo, for a reading caller.

    For a project on the GitHub store, a claim for a session this computer never ran cannot be verified
    here, so it is held; a session this computer ran holds the claim only while it drives the todo.
    Any other project keeps the local rule: the claim holds while its session is live.
    """
    if not is_github_backed(project_path):
        return await is_live_session_id(db, session_id)
    answer = await own_session_answer(db, project_path, slug, session_id)
    return answer is not OwnSessionAnswer.ENDED


async def claim_is_driven_here(db: Db, project_path: str | Path, slug: str, session_id: str) -> bool:
    """Return whether the claim naming ``session_id`` is a driver this computer runs, for its dispatch budget.

    On the GitHub store only a session this computer ran that still drives the todo counts; a claim held
    by another computer, or one this computer cannot verify, holds the todo without using this computer's
    slots. Any other project keeps the local rule: the claim counts while its session is live.
    """
    if not is_github_backed(project_path):
        return await is_live_session_id(db, session_id)
    return await own_session_answer(db, project_path, slug, session_id) is OwnSessionAnswer.HELD


async def find_live_prepare_worker_for_slug(db: Db, slug: str, command_value: str) -> str | None:
    """Return the newest live prepare worker id for an exact slug+command match.

    Prepare workers run on repo root (subdir=None). A bare ``startswith`` match
    is unsafe here because a colliding slug (``my-slug-extra``) would match a
    lookup for ``my-slug``. This helper requires the session title to equal
    ``/cmd slug`` or to be followed by whitespace, so longer slugs that begin
    with the target slug as a prefix cannot match.
    """
    sessions = await db.list_sessions(include_closed=False)
    for session in sessions:
        if session.subdir is not None:
            continue
        if session.working_slug == slug and _matches_command(session.command, command_value):
            return session.session_id
    return None


async def find_live_reviewer_for_slug(
    db: Db,
    project_path: str | Path,
    slug: str,
    command_value: str,
    subdir_override: str | None = None,
) -> str | None:
    """Return the newest live reviewer session for an exact project+slug+command match.

    Composes exact command and slug fields with :func:`_expected_subdir` for the
    per-slug scope, and :func:`_same_project_root`
    so a same-named slug in a different project never holds this subject — R1
    defines the subject as ``(project, slug, review command)``. This serves all
    three slug-bound reviewer families — ``/review-build`` runs in the slug
    worktree (default ``subdir_override``), while ``/review-plan`` and
    ``/review-architecture`` run at repo root (caller passes
    ``subdir_override=""``).
    """
    project_root = Path(project_path).resolve()
    expected_subdir = _expected_subdir(slug, subdir_override)
    sessions = await db.list_sessions(include_closed=False)
    for session in sessions:
        if session.subdir != expected_subdir:
            continue
        if not _same_project_root(session.project_path, project_root):
            continue
        if session.working_slug == slug and _matches_command(session.command, command_value):
            return session.session_id
    return None


def _same_project_root(session_project_path: str | None, project_root: Path) -> bool:
    """Return whether a session's stored project path resolves to ``project_root``.

    A session bound to a same-named slug in a different project must not block
    dispatch here, so ownership is scoped to the canonical project root. A session
    with no project path (or an unresolvable one) never matches.
    """
    if not session_project_path:
        return False
    try:
        return Path(session_project_path).resolve() == project_root
    except (OSError, ValueError):
        return False


def is_commit_reviewer_in_project(
    *, command: str | None, session_project_path: str | None, project_root: Path, command_value: str
) -> bool:
    """Return whether a session record is a commit reviewer working in ``project_root``."""
    return _same_project_root(session_project_path, project_root) and _matches_command(command, command_value)


async def list_live_commit_reviewers_for_initiator(
    db: Db,
    project_path: str | Path,
    initiator_session_id: str,
    command_value: str,
) -> tuple[tuple[str, str], ...]:
    """Return every live commit reviewer for this project and driver, with its mode.

    The dedup guard decides one subject and so asks for one holder. The commit
    gate's reuse hint is the opposite question: mode is part of the subject, so
    more than one reviewer is legitimately open, and naming an arbitrary one
    would route a code review to the doc-hygiene lane. Reporting every open
    reviewer beside its mode leaves the lane match to the reader that knows
    what it committed.
    """
    project_root = Path(project_path).resolve()
    sessions = await db.list_sessions(include_closed=False, initiator_session_id=initiator_session_id)
    return tuple(
        (session.session_id, session.thinking_mode or "")
        for session in sessions
        if is_commit_reviewer_in_project(
            command=session.command,
            session_project_path=session.project_path,
            project_root=project_root,
            command_value=command_value,
        )
    )


def _holds_commit_review_subject(
    *,
    command: str | None,
    session_project_path: str | None,
    session_thinking_mode: str | None,
    project_root: Path,
    command_value: str,
    thinking_mode: str,
) -> bool:
    """Return whether a session record holds the commit-review subject for this project and mode.

    The project/command/mode part of the subject is the same whichever driver
    form keys the lookup, so both driver lookups share it.
    """
    return session_thinking_mode == thinking_mode and is_commit_reviewer_in_project(
        command=command,
        session_project_path=session_project_path,
        project_root=project_root,
        command_value=command_value,
    )


async def find_live_commit_reviewer_for_initiator(
    db: Db,
    project_path: str | Path,
    initiator_session_id: str,
    command_value: str,
    thinking_mode: str,
) -> str | None:
    """Return the newest live commit-review session for this project, initiator, and mode.

    Commit review carries no todo slug — its subject is a commit series whose SHA
    set changes every remediation round, so slug-keyed dedup cannot reach it. For a
    caller that has a session, the subject is identified by the project, the driver
    (``initiator_session_id``) that opened the review, and the thinking mode the
    review runs at, scoped by :func:`_same_project_root` the same way the
    orchestrator-owner signal is, and filtered at the query layer via
    ``list_sessions(initiator_session_id=...)`` rather than a second in-process
    pass. A caller with no session is keyed by
    :func:`find_live_commit_reviewer_for_terminal_human`.

    Mode belongs to the subject because the review lanes differ in cost and in
    what they read: doc-hygiene and code review use different modes over snippet
    conformance and behavior. A mode-blind subject collapses them, so the
    cheap lane is refused as a duplicate of the expensive one and its work lands
    on the wrong reviewer. Two live reviewers at the same mode remain one
    subject and still dedup.

    This answers the guard's question — is this exact subject taken — so the
    mode is required. The commit gate's reuse hint asks a different question
    and uses :func:`list_live_commit_reviewers_for_initiator` instead.
    """
    project_root = Path(project_path).resolve()
    sessions = await db.list_sessions(include_closed=False, initiator_session_id=initiator_session_id)
    for session in sessions:
        if _holds_commit_review_subject(
            command=session.command,
            session_project_path=session.project_path,
            session_thinking_mode=session.thinking_mode,
            project_root=project_root,
            command_value=command_value,
            thinking_mode=thinking_mode,
        ):
            return session.session_id
    return None


async def find_live_commit_reviewer_for_terminal_human(
    db: Db,
    project_path: str | Path,
    human_email: str,
    command_value: str,
    thinking_mode: str,
) -> str | None:
    """Return the newest live commit-review session a terminal human started for this project and mode.

    A terminal caller has no session, so a reviewer it starts records no
    ``initiator_session_id`` and is found by the human it records instead. The
    empty-initiator condition keeps the two driver forms disjoint: a reviewer an
    agent session opened inherits its human's ``human_email`` but carries that
    session as its initiator, so it never holds its human's terminal subject.
    ``db.list_sessions`` has no filter for either field, so both are matched here.
    """
    project_root = Path(project_path).resolve()
    sessions = await db.list_sessions(include_closed=False)
    for session in sessions:
        if session.initiator_session_id:
            continue
        if (session.human_email or "").casefold() != human_email.casefold():
            continue
        if _holds_commit_review_subject(
            command=session.command,
            session_project_path=session.project_path,
            session_thinking_mode=session.thinking_mode,
            project_root=project_root,
            command_value=command_value,
            thinking_mode=thinking_mode,
        ):
            return session.session_id
    return None


async def _open_non_closing_sessions(db: Db) -> list[Session]:
    """Return every open session that is not closing, whatever its bootstrap state.

    One selection for "accepted start" and "holder": a session a create door just
    wrote is ``initializing`` and carries no ``active_runner`` yet, so a holder
    query limited to ``active`` sessions would not see it.
    """
    sessions = await db.list_sessions(all_open=True)
    return [session for session in sessions if session.lifecycle_status != SessionLifecycleStatus.CLOSING]


async def live_orchestrator_owner(db: Db, project_path: str | Path, slug: str) -> str | None:
    """Return the id of an open orchestrator bound to ``slug`` in this project.

    Authoritative orchestrator dedup signal: a session is the owner when it is an
    open, non-closing driver (a role of the workflow's driver set) from its
    creation on, still initializing included, its ``working_slug`` matches ``slug``
    exactly, and it runs in the same canonical project root. Exact slug equality
    (not a title/worktree heuristic) and project scoping mean one project's slug
    never blocks another's same-named slug. Returns ``None`` when no such session
    exists.
    """
    project_root = Path(project_path).resolve()
    for session in await _open_non_closing_sessions(db):
        if session.role not in DRIVER_ROLES:
            continue
        if session.working_slug != slug:
            continue
        if _same_project_root(session.project_path, project_root):
            return session.session_id
    return None


async def find_accepted_lifecycle_start(db: Db, project_path: str | Path, slug: str, role: str) -> str | None:
    """Return the open session already started as ``role``'s driver for ``slug`` in this project.

    Lifecycle dispatch's idempotency read: a session carrying the lane's driver role, this
    ``working_slug`` and this canonical project root, with no close timestamp and not closing, is
    the start an earlier dispatch already accepted, including one whose ``active_runner`` record
    failed. When several match, the earliest created is the first accepted start. Reads the
    session's own registry row and writes nothing. Returns ``None`` when no such session exists.
    """
    project_root = Path(project_path).resolve()
    matches = [
        session
        for session in await _open_non_closing_sessions(db)
        if session.role == role
        and session.working_slug == slug
        and _same_project_root(session.project_path, project_root)
    ]
    if not matches:
        return None
    return min(matches, key=lambda session: (session.created_at is None, session.created_at)).session_id


@dataclass(frozen=True)
class SlugHolders:
    """The two live-holder signals for a slug, resolved but not yet exempted.

    ``orchestrator_owner`` is a live orchestrator bound to the slug
    (:func:`live_orchestrator_owner`); ``live_runner`` is the slug's
    ``active_runner`` when it still names a live session. Either may be ``None``.
    ``foreign_claim`` is the slug's ``active_runner`` on a GitHub-backed project when it
    names a session this computer never ran: it blocks nothing here, because the master
    judges it, names its computer, or frees it when ended.
    Caller-exemption — is a holder the caller itself? — is applied by the
    dispatch guard for its launch class.
    """

    orchestrator_owner: str | None
    live_runner: str | None
    foreign_claim: str | None = None


async def resolve_slug_holders(
    db: Db,
    project_path: str | Path,
    slug: str,
    active_runner: str | None,
) -> SlugHolders:
    """Resolve the two live-holder signals for ``slug``.

    The single source of the holder algorithm for lifecycle dispatch guards: a
    live orchestrator bound to the slug, and a live ``active_runner`` claim.
    Liveness is checked here; precedence and caller-exemption are the caller's
    to apply. For a project on the GitHub store, ``live_runner`` is set only when the
    claim's session is this computer's own and still drives the todo; a claim for a
    session this computer never ran is returned as ``foreign_claim``, and a claim for
    one it ran that has ended is neither.
    """
    owner = await live_orchestrator_owner(db, project_path, slug)
    if not active_runner:
        return SlugHolders(orchestrator_owner=owner, live_runner=None)
    if not is_github_backed(project_path):
        live_runner = active_runner if await is_live_session_id(db, active_runner) else None
        return SlugHolders(orchestrator_owner=owner, live_runner=live_runner)
    answer = await own_session_answer(db, project_path, slug, active_runner)
    return SlugHolders(
        orchestrator_owner=owner,
        live_runner=active_runner if answer is OwnSessionAnswer.HELD else None,
        foreign_claim=active_runner if answer is OwnSessionAnswer.NOT_OWN else None,
    )


async def recheck_slug_holder(
    runtime_db: Db,
    todos_db: WorkflowStore,
    project_path: str | Path,
    slug: str,
    *,
    exempt_session_id: str | None,
) -> str | None:
    """Return the session holding ``slug`` as a driver on this computer, or ``None`` when no other session does.

    The narrow holder re-check taken inside :func:`driver_start_section`: the slug's own
    ``active_runner`` and the registry owner through :func:`resolve_slug_holders`, with no
    project-wide load and no writes. ``exempt_session_id`` is treated as no holder. A claim for a
    session this computer never ran is not a holder here; the master judges it.
    """
    state = await todos_db.read_state(slug)
    raw_runner = state.get(ACTIVE_RUNNER_STATE_KEY) if state is not None else None
    active_runner = raw_runner if isinstance(raw_runner, str) else None
    holders = await resolve_slug_holders(runtime_db, project_path, slug, active_runner)
    for holder in (holders.orchestrator_owner, holders.live_runner):
        if holder is not None and holder != exempt_session_id:
            return holder
    return None


async def live_orchestrator_owned_slugs(db: Db, project_path: str | Path) -> set[str]:
    """Return the slugs owned by an open orchestrator in this project, in one pass.

    The set-returning sibling of :func:`live_orchestrator_owner` lets the pure
    ``decide_dispatches`` stay synchronous — the single async registry read happens
    once in the runner caller, and the precomputed set is the orchestrator-dedup
    signal for the project-scoped full-set evaluation. An orchestrator still
    initializing owns its slug.
    """
    project_root = Path(project_path).resolve()
    return {
        session.working_slug
        for session in await _open_non_closing_sessions(db)
        if session.role in DRIVER_ROLES
        and session.working_slug
        and _same_project_root(session.project_path, project_root)
    }
