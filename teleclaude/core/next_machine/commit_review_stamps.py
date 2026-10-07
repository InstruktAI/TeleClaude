"""Commit-review stamps — the durable, per-SHA outcome of reviewing a commit on main.

A reviewer stamps its verdict on the commits it reviewed; an author stamps
``approve`` with a reason on a review candidate that owes no review. Both land
as ``events`` items on the todo whose lifecycle claim the stamping session — or
the session that started it — holds, so the lifecycle reads the outcome from
the todo state it already owns. The latest stamp on a SHA is its outcome.

The same module owns the reads the prepare state machine makes of those
records: the commits a session authored on main while holding its prepare
claim, paired with their current outcome. Nothing here judges whether a commit
owes review; that stays with the authoring agent.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from instrukt_ai_logging import get_logger

from teleclaude.commit_identity import SESSION_TRAILER_KEY
from teleclaude.core.db import get_session_field_sync
from teleclaude.core.next_machine.git_ops import run_git_command
from teleclaude.core.next_machine.state_mutation import StateWriter
from teleclaude.core.todos_db import get_todos_db
from teleclaude.paths import MAIN_DB_PATH
from teleclaude.project_root import resolve_project_root
from teleclaude.types.state_value import StateValue
from teleclaude.types.todos import (
    CommitReviewDetail,
    CommitReviewVerdict,
    Event,
    PrepareClaimDetail,
    TodoEventKind,
)

logger = get_logger(__name__)

__all__ = [
    "CommitOutcome",
    "CommitReviewStampRefused",
    "OutstandingCommit",
    "StampResult",
    "apply_commit_review_stamp",
    "current_outcomes",
    "outstanding_claim_period_commits",
]

_MAIN_REF = "main"
_WORKING_SLUG_FIELD = "working_slug"
_INITIATOR_FIELD = "initiator_session_id"
_COMMIT_REF_TEMPLATE = "{sha}^{{commit}}"
_GIT_REV_PARSE_VERIFY = ["rev-parse", "--verify", "--quiet"]
_GIT_IS_ANCESTOR = ["merge-base", "--is-ancestor"]
_GIT_LOG = "log"
_GIT_FIXED_STRINGS = "--fixed-strings"
_RANGE_TEMPLATE = "{base}..{tip}"
_GIT_LOG_NO_WALK = ["log", "--no-walk"]
_GREP_TEMPLATE = "--grep={key}: {session_id}"
_LOG_STAMP_APPLIED = "commit_review_stamp"
_LOG_STAMP_NO_STATE = "commit_review_stamp_no_state"
_FIELD_SEP = "\x1f"
_RECORD_SEP = "\x1e"
_RECORD_LINE_ENDINGS = "\r\n"
_TRAILER_VALUE_SEP = ","
_LOG_FORMAT = "--format=%H%x1f%(trailers:key={key},valueonly,unfold,separator=%x2c)%x1e"

_ERR_NO_SESSION = "a commit-review stamp requires a stamping session"
_ERR_NO_SHAS = "a commit-review stamp requires at least one commit SHA"
_ERR_UNRESOLVED_SHA = "{sha!r} does not resolve to a commit: {detail}"
_ERR_NOT_ON_MAIN = "{sha} is not reachable from main; only commits on main can be stamped"
_ERR_CLAIM_WITHOUT_BOUNDARY = (
    "the prepare claim of session {session_id} records no main boundary; its claim period cannot be read"
)
_ERR_GIT_LOG = "cannot read commits on main: {detail}"


class CommitReviewStampRefused(ValueError):
    """Raised when a stamp request is refused before anything is written."""


@dataclass(frozen=True)
class CommitOutcome:
    """The current outcome of one commit: its latest stamp."""

    sha: str
    verdict: CommitReviewVerdict
    stamped_by: str
    stamped_at: str
    reason: str


@dataclass(frozen=True)
class OutstandingCommit:
    """A claim-period commit that holds no ``approve`` stamp."""

    sha: str
    verdict: CommitReviewVerdict | None


@dataclass(frozen=True)
class StampResult:
    """What one stamp request recorded and which sessions' review gate it discharges."""

    slug: str | None
    shas: tuple[str, ...]
    verdict: CommitReviewVerdict
    discharged_sessions: tuple[str, ...]


def current_outcomes(events: list[Event]) -> dict[str, CommitOutcome]:
    """Return each stamped SHA's current outcome — the latest stamp event for it."""
    outcomes: dict[str, CommitOutcome] = {}
    for event in events:
        if event.kind != TodoEventKind.COMMIT_REVIEW_STAMP:
            continue
        sha = event.details.get(CommitReviewDetail.SHA)
        verdict = event.details.get(CommitReviewDetail.VERDICT)
        if not isinstance(sha, str) or not isinstance(verdict, str):
            continue
        reason = event.details.get(CommitReviewDetail.REASON)
        outcomes[sha] = CommitOutcome(
            sha=sha,
            verdict=CommitReviewVerdict(verdict),
            stamped_by=event.actor,
            stamped_at=event.at,
            reason=reason if isinstance(reason, str) else "",
        )
    return outcomes


def outstanding_claim_period_commits(
    project_root: str, session_id: str, events: list[Event]
) -> list[OutstandingCommit]:
    """Return the session's claim-period commits on main that hold no ``approve`` stamp.

    The claim period is the commits on main after the main HEAD the session's
    latest prepare-claim event recorded; a session that recorded no claim owes
    nothing, and a claim recorded without its boundary raises. A commit belongs
    to the session when its ``Session:`` trailer names it.
    """
    claim_head = _latest_claim_boundary(events, session_id)
    if claim_head is None:
        return []
    outcomes = current_outcomes(events)
    outstanding: list[OutstandingCommit] = []
    for commit_sha, sessions in _main_commits_by_session(project_root, session_id, claim_head):
        if session_id not in sessions:
            continue
        outcome = outcomes.get(commit_sha)
        if outcome is not None and outcome.verdict is CommitReviewVerdict.APPROVE:
            continue
        outstanding.append(OutstandingCommit(sha=commit_sha, verdict=outcome.verdict if outcome else None))
    return outstanding


async def apply_commit_review_stamp(
    *,
    cwd: str,
    session_id: str,
    shas: list[str],
    verdict: CommitReviewVerdict,
    reason: str,
) -> StampResult:
    """Record one stamp per SHA on the todo the stamping session's chain claims.

    Every SHA resolves to its full id and must be reachable from main, or the
    whole request is refused before any write. The stamp lands on the stamping
    session's ``working_slug``, else on its initiator's; with neither it lands
    on no todo and still reports the sessions whose review gate it discharges.
    """
    if not session_id:
        raise CommitReviewStampRefused(_ERR_NO_SESSION)
    if not shas:
        raise CommitReviewStampRefused(_ERR_NO_SHAS)
    project_root = str(resolve_project_root(cwd))
    full_shas = tuple(dict.fromkeys(await asyncio.to_thread(_resolve_main_commits, project_root, shas)))
    initiator = _read_session_text(session_id, _INITIATOR_FIELD)
    slug = _read_session_text(session_id, _WORKING_SLUG_FIELD) or (
        _read_session_text(initiator, _WORKING_SLUG_FIELD) if initiator else None
    )
    if slug:
        await _append_stamps(project_root, slug, session_id, full_shas, verdict, reason)
    chain = {session_id} if initiator is None else {session_id, initiator}
    authored_by = await asyncio.to_thread(_commit_sessions, project_root, full_shas)
    discharged = tuple(sorted(chain & authored_by))
    logger.info(
        _LOG_STAMP_APPLIED,
        slug=slug,
        shas=len(full_shas),
        verdict=verdict.value,
        stamping_session=session_id,
    )
    return StampResult(slug=slug, shas=full_shas, verdict=verdict, discharged_sessions=discharged)


async def _append_stamps(
    project_root: str,
    slug: str,
    session_id: str,
    shas: tuple[str, ...],
    verdict: CommitReviewVerdict,
    reason: str,
) -> None:
    todos_db = await get_todos_db(project_root)
    raw_state = await todos_db.read_state(slug)
    if raw_state is None:
        logger.warning(_LOG_STAMP_NO_STATE, slug=slug, stamping_session=session_id)
        return
    writer = StateWriter(raw_state)
    stamped_at = datetime.now(UTC).isoformat()
    for sha in shas:
        details: dict[str, StateValue] = {CommitReviewDetail.SHA: sha, CommitReviewDetail.VERDICT: verdict.value}
        if reason:
            details[CommitReviewDetail.REASON] = reason
        writer.state.events.append(
            Event(at=stamped_at, actor=session_id, kind=TodoEventKind.COMMIT_REVIEW_STAMP, details=details)
        )
    await writer.commit(todos_db, slug)


def _read_session_text(session_id: str | None, field: str) -> str | None:
    if not session_id:
        return None
    value = get_session_field_sync(str(MAIN_DB_PATH), session_id, field)
    return value if isinstance(value, str) and value else None


def _latest_claim_boundary(events: list[Event], session_id: str) -> str | None:
    """Return the main HEAD the session's latest prepare-claim event recorded.

    ``None`` means the session recorded no claim on the todo. A claim event that
    carries no boundary is a contract violation and fails closed.
    """
    claim: Event | None = None
    for event in events:
        if event.kind == TodoEventKind.PREPARE_CLAIM and event.actor == session_id:
            claim = event
    if claim is None:
        return None
    recorded = claim.details.get(PrepareClaimDetail.MAIN_HEAD)
    if not isinstance(recorded, str) or not recorded:
        raise RuntimeError(_ERR_CLAIM_WITHOUT_BOUNDARY.format(session_id=session_id))
    return recorded


def _resolve_main_commits(project_root: str, shas: list[str]) -> list[str]:
    resolved: list[str] = []
    for sha in shas:
        returncode, stdout, stderr = run_git_command(
            [*_GIT_REV_PARSE_VERIFY, _COMMIT_REF_TEMPLATE.format(sha=sha)], project_root
        )
        if returncode != 0 or not stdout.strip():
            raise CommitReviewStampRefused(_ERR_UNRESOLVED_SHA.format(sha=sha, detail=stderr.strip() or "unknown"))
        full_sha = stdout.strip()
        returncode, _, _ = run_git_command([*_GIT_IS_ANCESTOR, full_sha, _MAIN_REF], project_root)
        if returncode != 0:
            raise CommitReviewStampRefused(_ERR_NOT_ON_MAIN.format(sha=full_sha))
        resolved.append(full_sha)
    return resolved


def _main_commits_by_session(project_root: str, session_id: str, after_sha: str) -> list[tuple[str, frozenset[str]]]:
    """Return ``(sha, Session trailer values)`` for main commits after *after_sha* naming *session_id*."""
    returncode, stdout, stderr = run_git_command(
        [
            _GIT_LOG,
            _RANGE_TEMPLATE.format(base=after_sha, tip=_MAIN_REF),
            _GIT_FIXED_STRINGS,
            _GREP_TEMPLATE.format(key=SESSION_TRAILER_KEY, session_id=session_id),
            _LOG_FORMAT.format(key=SESSION_TRAILER_KEY),
        ],
        project_root,
    )
    if returncode != 0:
        raise RuntimeError(_ERR_GIT_LOG.format(detail=stderr.strip() or "unknown"))
    return _parse_log_records(stdout)


def _commit_sessions(project_root: str, shas: tuple[str, ...]) -> frozenset[str]:
    """Return the distinct ``Session:`` trailer values of *shas*."""
    sessions: set[str] = set()
    for sha in shas:
        returncode, stdout, stderr = run_git_command(
            [*_GIT_LOG_NO_WALK, _LOG_FORMAT.format(key=SESSION_TRAILER_KEY), sha], project_root
        )
        if returncode != 0:
            raise RuntimeError(_ERR_GIT_LOG.format(detail=stderr.strip() or "unknown"))
        for _, trailer_sessions in _parse_log_records(stdout):
            sessions |= trailer_sessions
    return frozenset(sessions)


def _parse_log_records(stdout: str) -> list[tuple[str, frozenset[str]]]:
    records: list[tuple[str, frozenset[str]]] = []
    for record in stdout.split(_RECORD_SEP):
        text = record.strip(_RECORD_LINE_ENDINGS)
        if not text:
            continue
        commit_sha, trailer_values = text.split(_FIELD_SEP)
        sessions = frozenset(value.strip() for value in trailer_values.split(_TRAILER_VALUE_SEP) if value.strip())
        records.append((commit_sha, sessions))
    return records
