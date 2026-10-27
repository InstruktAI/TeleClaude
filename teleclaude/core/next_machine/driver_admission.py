"""Fleet-wide admission of a GitHub-backed todo's driver, decided on the master.

A todo on the GitHub workflow store is visible to every computer with a checkout, so no one
computer's session registry can say whether it is already driven. Every start of such a todo is
admitted by the fleet's master (`local/projects/teleclaude/adr/0135-github-backed-driver-starts-are-admitted-by-the-mesh-master`),
which records the claim before the session exists, and every claim write for such a todo runs on
the master inside the todo's start section against an item refreshed from GitHub
(`local/projects/teleclaude/adr/0136-only-the-master-writes-a-github-backed-claim`). Each computer
answers only for the sessions it ran (:func:`~teleclaude.core.next_machine.runtime.sessions.own_session_answer`);
the master asks every known computer and treats silence as held.

This module holds the master's side: judging a claim, deciding an admission, releasing a claim, and
reconciling the claims no one released.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Coroutine, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from http import HTTPMethod
from pathlib import Path
from typing import Any

from instrukt_ai_logging import get_logger
from pydantic import BaseModel, ConfigDict
from redis.exceptions import RedisError

from teleclaude.caller_identity import cleared_command_path
from teleclaude.config.machine import config
from teleclaude.config.registered_homes import project_identity_for_folder
from teleclaude.constants import SYSTEM_DAEMON_PRINCIPAL
from teleclaude.core.command_dispatch import RemoteDispatchError, RemoteDispatchReason
from teleclaude.core.db import Db, get_db
from teleclaude.core.inbound.fleet import MasterUnavailability, known_computer_names, observe_fleet_from_heartbeats
from teleclaude.core.next_machine.driver_claim import set_active_runner
from teleclaude.core.next_machine.runner_types import RunnerLane, RunnerTodo
from teleclaude.core.next_machine.runtime.driver_starts import driver_start_section
from teleclaude.core.next_machine.runtime.sessions import (
    OwnSessionAnswer,
    is_github_backed,
    own_session_answer,
    recheck_slug_holder,
)
from teleclaude.core.relay_carrier import carry_request
from teleclaude.core.todos_db._exceptions import (
    AdmissionUnavailable,
    AdmissionUnavailableReason,
    ClaimConflict,
    DriverStartBusy,
    OperationFailure,
)
from teleclaude.core.workflow_store.github_store import refresh_github_workflow_store
from teleclaude.core.workflow_store.store import get_workflow_store
from teleclaude.types.commands import RelayedResponse
from teleclaude.types.todos import ACTIVE_RUNNER_STATE_KEY

logger = get_logger(__name__)

SESSION_ANSWER_PATH = "/todos/session-answer"
ADMISSION_PATH = "/todos/driver-admission"
RELEASE_PATH = "/todos/driver-release"

# The waits nest: a question to a computer < the master's answer to an admission < the relay deadline
# of that admission < the start's whole budget, which leaves room inside the request timeout of
# ``TelecAPIClient.run_session`` for the guard before it and the session creation after it. Every wait
# is on a task that keeps running when its waiter gives up, so no GitHub write is cancelled midway;
# what such a task leaves behind is released by its start or reconciled by the master.
QUESTION_DEADLINE_S = 4.0
ADMISSION_BUDGET_S = 7.0
ADMISSION_RELAY_DEADLINE_S = 9.0
RELEASE_RELAY_DEADLINE_S = 9.0
START_BUDGET_S = 12.0

_JSON_CONTENT_TYPE = "application/json"
_PROJECT_PATH_FIELD = "project_path"
_SLUG_FIELD = "slug"
_SESSION_ID_FIELD = "session_id"
_ANSWER_FIELD = "answer"
_COMPUTER_SEPARATOR = ", "
_JUDGED_EVENT = "driver claim judged"
_QUESTION_UNANSWERED_EVENT = "driver claim question unanswered"
_ADMITTED_EVENT = "driver start admitted"
_REFUSED_EVENT = "driver start refused by held claim"
_RELEASED_EVENT = "driver claim released"
_RECONCILED_EVENT = "driver claim reconciled"
_RECONCILE_SKIPPED_EVENT = "driver claim reconciliation skipped"
ADMISSION_CONFLICT_KIND = "driver_admission_conflict"
_KIND_FIELD = "kind"
_SUMMARY_FIELD = "summary"


class DriverAdmissionRequest(BaseModel):
    """The wire body asking the master to admit a start of a GitHub-backed todo's driver."""

    model_config = ConfigDict(frozen=True)
    project_path: str
    slug: str
    session_id: str
    lane: RunnerLane
    manually_started: bool
    release_hold: bool


class DriverReleaseRequest(BaseModel):
    """The wire body asking the master to release the claim naming a session."""

    model_config = ConfigDict(frozen=True)
    project_path: str
    slug: str
    session_id: str


@dataclass(frozen=True)
class AdmissionCaller:
    """The principal a relayed admission, question or release is cleared as on the receiving computer.

    A request issued for a start carries that start's principal and the command it cleared; the
    daemon's own acts (housekeeping, reconciliation) carry the daemon principal and no command. No new
    principal is minted.
    """

    principal: str = SYSTEM_DAEMON_PRINCIPAL
    cleared_command: str | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class ClaimJudgment:
    """Whether a claim still holds its todo, and who said so.

    ``computer`` names the computer that answered ``HELD`` for the session; ``unanswered`` names the
    computers that did not answer when no computer answered for it.
    """

    held: bool
    computer: str | None = None
    unanswered: tuple[str, ...] = ()


@dataclass(frozen=True)
class StartRequest:
    """One driver start of a GitHub-backed todo, as the master decides it."""

    project_root: Path
    slug: str
    session_id: str
    lane: RunnerLane
    manually_started: bool
    release_hold: bool
    caller: AdmissionCaller

    def to_body(self) -> bytes:
        """The admission request body, naming the project by the identity another computer resolves."""
        return (
            DriverAdmissionRequest(
                project_path=project_identity_for_folder(self.project_root),
                slug=self.slug,
                session_id=self.session_id,
                lane=self.lane,
                manually_started=self.manually_started,
                release_hold=self.release_hold,
            )
            .model_dump_json()
            .encode()
        )


async def _carry(
    destination: str,
    method: HTTPMethod,
    path: str,
    *,
    query: list[list[str]],
    body: bytes,
    caller: AdmissionCaller,
    deadline_s: float,
) -> RelayedResponse:
    """Carry one request to ``destination`` as ``caller`` and return the complete response it gave."""
    result = await carry_request(
        destination=destination,
        method=method.value,
        path=path,
        query=query,
        body=body,
        content_type=_JSON_CONTENT_TYPE if body else None,
        principal=caller.principal,
        caller_session_id=caller.session_id,
        cleared_command=cleared_command_path(caller.cleared_command) if caller.cleared_command else None,
        deadline_s=deadline_s,
    )
    return RelayedResponse.from_wire(result if isinstance(result, dict) else None)


def _answer_of(response: RelayedResponse) -> OwnSessionAnswer | None:
    """The answer a computer gave to the session question, or ``None`` when it gave none the master can read."""
    if response.status_code != 200:
        return None
    try:
        payload: object = json.loads(base64.b64decode(response.body_b64))
        if not isinstance(payload, dict):
            return None
        return OwnSessionAnswer(payload.get(_ANSWER_FIELD))
    except (ValueError, UnicodeError):
        return None


async def _ask_computer(
    computer: str, project_root: Path, slug: str, session_id: str, caller: AdmissionCaller
) -> tuple[str, OwnSessionAnswer | None]:
    """Ask one computer about a session; silence of any kind is ``None``."""
    query = [
        [_PROJECT_PATH_FIELD, project_identity_for_folder(project_root)],
        [_SLUG_FIELD, slug],
        [_SESSION_ID_FIELD, session_id],
    ]
    try:
        response = await _carry(
            computer,
            HTTPMethod.GET,
            SESSION_ANSWER_PATH,
            query=query,
            body=b"",
            caller=caller,
            deadline_s=QUESTION_DEADLINE_S,
        )
    except (RemoteDispatchError, RuntimeError, ValueError) as error:
        logger.warning(
            _QUESTION_UNANSWERED_EVENT, computer=computer, slug=slug, session_id=session_id, error=str(error)
        )
        return computer, None
    answer = _answer_of(response)
    if answer is None:
        logger.warning(
            _QUESTION_UNANSWERED_EVENT, computer=computer, slug=slug, session_id=session_id, status=response.status_code
        )
    return computer, answer


async def judge_claim(
    project_root: Path, slug: str, session_id: str, *, caller: AdmissionCaller = AdmissionCaller()
) -> ClaimJudgment:
    """Judge whether the claim naming ``session_id`` still holds ``slug``, as the master.

    The master's own registry answers first. When it never ran the session it asks every other known
    computer in parallel. A computer answering ``HELD`` or ``ENDED`` decides; every computer answering
    ``NOT_OWN`` means the session ended unrecorded; anything else, a computer that did not answer, is
    held, with the computers that did not answer named.
    """
    local = config.computer.name
    db = await get_db()
    own = await own_session_answer(db, project_root, slug, session_id)
    if own is OwnSessionAnswer.HELD:
        return ClaimJudgment(held=True, computer=local)
    if own is OwnSessionAnswer.ENDED:
        return ClaimJudgment(held=False)
    others = sorted(known_computer_names() - {local})
    answers = await asyncio.gather(*(_ask_computer(name, project_root, slug, session_id, caller) for name in others))
    for computer, answer in answers:
        if answer is OwnSessionAnswer.HELD:
            return ClaimJudgment(held=True, computer=computer)
    if any(answer is OwnSessionAnswer.ENDED for _, answer in answers):
        return ClaimJudgment(held=False)
    unanswered = tuple(computer for computer, answer in answers if answer is None)
    judgment = ClaimJudgment(held=bool(unanswered), unanswered=unanswered)
    logger.info(
        _JUDGED_EVENT,
        project=str(project_root),
        slug=slug,
        session_id=session_id,
        held=judgment.held,
        unanswered=_COMPUTER_SEPARATOR.join(unanswered),
    )
    return judgment


async def decide_driver_admission(request: StartRequest) -> None:
    """Admit ``request.session_id`` as the driver of its todo, or refuse naming the holder; run on the master.

    Runs inside the todo's start section, against the item just refreshed from GitHub. The master's
    local holder re-check exempts the starting session; a claim naming another session is judged, and a
    held claim raises :class:`ClaimConflict` naming the holding session and the computer that answered
    for it, or the computers that did not answer. Otherwise the claim is written through the one claim
    writer, replacing an ended claim in the same write. A todo with no live state (missing, removed or
    delivered) has nothing to record a claim on, so the start is refused as :class:`AdmissionUnavailable`:
    an admission always has recorded its claim.
    """
    project_root, slug = request.project_root, request.slug
    await refresh_github_workflow_store(project_root, computer=config.computer.name)
    todos_db = await get_workflow_store(project_root)
    holder = await recheck_slug_holder(
        await get_db(), todos_db, project_root, slug, exempt_session_id=request.session_id
    )
    if holder is not None:
        raise ClaimConflict(slug=slug, holder=holder, computer=config.computer.name)
    state = await todos_db.read_state(slug)
    if state is None:
        raise AdmissionUnavailable(slug=slug, reason=AdmissionUnavailableReason.NO_LIVE_TODO)
    claim = state.get(ACTIVE_RUNNER_STATE_KEY)
    if isinstance(claim, str) and claim and claim != request.session_id:
        judgment = await judge_claim(project_root, slug, claim, caller=request.caller)
        if judgment.held:
            logger.warning(
                _REFUSED_EVENT,
                project=str(project_root),
                slug=slug,
                session_id=request.session_id,
                holder=claim,
                computer=judgment.computer,
                unanswered=_COMPUTER_SEPARATOR.join(judgment.unanswered),
            )
            raise ClaimConflict(slug=slug, holder=claim, computer=judgment.computer, unanswered=judgment.unanswered)
    recorded = await set_active_runner(
        todos_db,
        slug,
        request.session_id,
        lane=request.lane,
        manually_started=request.manually_started,
        release_hold=request.release_hold,
    )
    if not recorded:
        raise AdmissionUnavailable(slug=slug, reason=AdmissionUnavailableReason.NO_LIVE_TODO)
    logger.info(_ADMITTED_EVENT, project=str(project_root), slug=slug, session_id=request.session_id)


async def clear_matching_claim(project_root: Path, slug: str, session_id: str) -> bool:
    """Clear the claim on ``slug`` while it still names ``session_id``; run on the master inside the todo's section.

    The item is refreshed from GitHub first so the clear is written against what GitHub holds. Returns
    whether a claim was cleared.
    """
    await refresh_github_workflow_store(project_root, computer=config.computer.name)
    todos_db = await get_workflow_store(project_root)
    cleared = False
    for row in await todos_db.list_todo(include_icebox=True, include_delivered=True, include_removed=True):
        if row["slug"] == slug and await todos_db.clear_active_runner_if_matches(row["id"], session_id):
            cleared = True
    if cleared:
        logger.info(_RELEASED_EVENT, project=str(project_root), slug=slug, session_id=session_id)
    return cleared


async def release_driver_claim(project_root: Path, slug: str, session_id: str) -> bool:
    """Release the claim naming ``session_id`` on ``slug``, in the todo's section; run on the master.

    A section held by another start refuses at once as busy, and the claim is left to the master's
    reconciliation.
    """
    async with driver_start_section(project_root, slug, starting_session_id=None):
        return await clear_matching_claim(project_root, slug, session_id)


async def reconcile_ended_claims(
    runtime_db: Db, project_root: Path, todos: Mapping[str, RunnerTodo]
) -> dict[str, RunnerTodo]:
    """Clear every claim the master's runner pass finds ended; return the todos as cleared.

    Acts only on the master and only for a project on the GitHub store. For each todo whose claim is not
    held by a session on the master, take the todo's section (busy skips this pass), judge the claim
    against the item just refreshed, and clear it when it is ended. This frees a todo whose release never
    arrived, or whose start gave up after the master recorded its claim. A fleet with no unique live master
    reconciles nothing this pass.
    """
    reconciled = dict(todos)
    if not is_github_backed(project_root):
        return reconciled
    candidates: list[tuple[str, RunnerTodo, str]] = []
    for slug, todo in todos.items():
        claim = todo.active_runner
        if claim and await own_session_answer(runtime_db, project_root, slug, claim) is not OwnSessionAnswer.HELD:
            candidates.append((slug, todo, claim))
    if not candidates:
        return reconciled
    try:
        if await resolve_admission_master(candidates[0][0]) is not None:
            return reconciled
    except AdmissionUnavailable as unavailable:
        logger.info(_RECONCILE_SKIPPED_EVENT, project=str(project_root), reason=unavailable.reason.value)
        return reconciled
    for slug, todo, claim in candidates:
        try:
            async with driver_start_section(project_root, slug, starting_session_id=None):
                if await _clear_ended_claim(project_root, slug, claim):
                    reconciled[slug] = replace(todo, active_runner=None, manually_started=False)
        except DriverStartBusy:
            continue
    return reconciled


async def _clear_ended_claim(project_root: Path, slug: str, claim: str) -> bool:
    """Judge ``claim`` against the refreshed item and clear it when ended; run inside the todo's section."""
    await refresh_github_workflow_store(project_root, computer=config.computer.name)
    todos_db = await get_workflow_store(project_root)
    state = await todos_db.read_state(slug)
    current = state.get(ACTIVE_RUNNER_STATE_KEY) if state is not None else None
    if current != claim:
        return False
    judgment = await judge_claim(project_root, slug, claim)
    if judgment.held:
        return False
    cleared = await clear_matching_claim(project_root, slug, claim)
    if cleared:
        logger.info(_RECONCILED_EVENT, project=str(project_root), slug=slug, session_id=claim)
    return cleared


async def resolve_admission_master(slug: str) -> str | None:
    """Name the computer that admits starts when it is not this one; ``None`` when this computer is it.

    The master is resolved as person messaging resolves it: the fleet's unique live master. Raises
    :class:`AdmissionUnavailable` naming why there is none. A fleet that cannot be observed establishes
    no master on any computer, this one included, so no start is admitted.
    """
    try:
        fleet = await observe_fleet_from_heartbeats()
    except (OSError, RedisError) as error:
        raise AdmissionUnavailable(
            slug=slug, reason=AdmissionUnavailableReason.FLEET_NOT_OBSERVABLE, detail=str(error)
        ) from error
    resolution = fleet.resolve_master()
    if resolution.master is None:
        reason = (
            AdmissionUnavailableReason.CONFLICTING_MASTERS
            if resolution.unavailability is MasterUnavailability.CONFLICTING_MASTERS
            else AdmissionUnavailableReason.NO_LIVE_MASTER
        )
        raise AdmissionUnavailable(
            slug=slug, reason=reason, detail=_COMPUTER_SEPARATOR.join(resolution.computers) or None
        )
    return None if resolution.master.name == config.computer.name else resolution.master.name


_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()  # guard: any-type - tasks of every result type are held here
_TASK_REFUSED_EVENT = "driver admission task refused after its waiter gave up"
_TASK_FAILED_EVENT = "driver admission task failed"


def spawn_tracked[Result](work: Coroutine[object, object, Result]) -> asyncio.Task[Result]:
    """Run ``work`` as a task that outlives its waiter, kept referenced and its failure logged.

    A waiter that gives up leaves the task running, so a GitHub write already begun is never cancelled
    midway. The failure of a task nobody waits on any longer is logged rather than lost.
    """
    task = asyncio.ensure_future(work)
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    task.add_done_callback(_log_task_outcome)
    return task


def _log_task_outcome[Result](task: asyncio.Task[Result]) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is None:
        return
    if isinstance(error, OperationFailure):
        logger.info(_TASK_REFUSED_EVENT, error=error.summary())
        return
    logger.error(_TASK_FAILED_EVENT, exc_info=(type(error), error, error.__traceback__))


async def _admission_on_master(request: StartRequest) -> None:
    async with driver_start_section(request.project_root, request.slug, starting_session_id=request.session_id):
        await decide_driver_admission(request)


async def admit_relayed_start(request: StartRequest) -> None:
    """Admit a start another computer relayed here; answer within the admission budget.

    Refuses with :class:`AdmissionUnavailable` unless this computer is the fleet's unique live master. The
    admission runs as a task that owns the todo's section on this computer; when the budget expires first
    the waiter is refused as undecided and the task finishes on its own, leaving a claim the starting
    computer's release or the master's reconciliation clears.
    """
    if await resolve_admission_master(request.slug) is not None:
        raise AdmissionUnavailable(slug=request.slug, reason=AdmissionUnavailableReason.NOT_THE_MASTER)
    task = spawn_tracked(_admission_on_master(request))
    try:
        await asyncio.wait_for(asyncio.shield(task), ADMISSION_BUDGET_S)
    except TimeoutError as error:
        raise AdmissionUnavailable(
            slug=request.slug, reason=AdmissionUnavailableReason.UNDECIDED_WITHIN_BUDGET
        ) from error


async def release_relayed_claim(project_root: Path, slug: str, session_id: str) -> bool:
    """Release a claim another computer asked this master to release; refuse unless this computer is the master."""
    if await resolve_admission_master(slug) is not None:
        raise AdmissionUnavailable(slug=slug, reason=AdmissionUnavailableReason.NOT_THE_MASTER)
    return await release_driver_claim(project_root, slug, session_id)


_HTTP_OK = 200
_HTTP_CONFLICT = 409
_HTTP_LOCKED = 423
_HTTP_UNAVAILABLE = 503
_DETAIL_FIELD = "detail"
_ADMISSION_DECLINED_STATUS = "status {status}"
_START_RELEASED_EVENT = "driver start withdrew its claim"
_START_FAILED_EVENT = "driver start failed before it was decided"
_RELEASE_UNANSWERED_EVENT = "driver claim release left to reconciliation"
_RELEASE_SKIPPED_EVENT = "driver claim release skipped while a start of the todo is in progress"


@dataclass
class _StartState:
    """Whether the caller of a start is still waiting for its outcome."""

    waiting: bool = True


def _detail_of(response: RelayedResponse) -> Mapping[str, object]:
    """The payload a refusing master carried as its response detail; empty when it carried none."""
    try:
        payload: object = json.loads(base64.b64decode(response.body_b64))
    except (ValueError, UnicodeError):
        return {}
    detail = payload.get(_DETAIL_FIELD) if isinstance(payload, dict) else None
    return {str(key): value for key, value in detail.items()} if isinstance(detail, dict) else {}


async def _post_to_master(
    master: str, slug: str, path: str, body: bytes, caller: AdmissionCaller, deadline_s: float
) -> RelayedResponse:
    """Carry a request to the master; a crossing that fails is :class:`AdmissionUnavailable`, never success."""
    try:
        return await _carry(master, HTTPMethod.POST, path, query=[], body=body, caller=caller, deadline_s=deadline_s)
    except RemoteDispatchError as error:
        reason = (
            AdmissionUnavailableReason.MASTER_CANNOT_CARRY
            if error.reason is RemoteDispatchReason.RELAY_UNSUPPORTED
            else AdmissionUnavailableReason.MASTER_DID_NOT_ANSWER
        )
        raise AdmissionUnavailable(slug=slug, reason=reason, detail=str(error)) from error
    except (RuntimeError, ValueError) as error:
        raise AdmissionUnavailable(
            slug=slug, reason=AdmissionUnavailableReason.MASTER_DID_NOT_ANSWER, detail=str(error)
        ) from error


async def _request_admission(master: str, request: StartRequest) -> None:
    """Ask the master to admit the start; its refusal is raised as the failure it names."""
    slug = request.slug
    response = await _post_to_master(
        master, slug, ADMISSION_PATH, request.to_body(), request.caller, ADMISSION_RELAY_DEADLINE_S
    )
    if response.status_code == _HTTP_OK:
        return
    detail = _detail_of(response)
    if response.status_code == _HTTP_CONFLICT:
        raise ClaimConflict.from_error_payload(slug, detail)
    if response.status_code == _HTTP_LOCKED:
        raise DriverStartBusy.from_error_payload(slug, detail)
    if response.status_code == _HTTP_UNAVAILABLE:
        declared = AdmissionUnavailable.from_error_payload(slug, detail)
        if declared is not None:
            raise declared
    raise AdmissionUnavailable(
        slug=slug,
        reason=AdmissionUnavailableReason.MASTER_CANNOT_CARRY,
        detail=_ADMISSION_DECLINED_STATUS.format(status=response.status_code),
    )


async def _release_within_section(project_root: Path, slug: str, session_id: str, caller: AdmissionCaller) -> None:
    """Ask the master to release the claim naming ``session_id``; run inside this computer's section for the todo.

    On the master the clear is made here. On another computer the request is relayed and its answer awaited
    until the relay deadline. A release that does not reach the master, or that the master refuses as busy,
    is logged and left to the master's reconciliation.
    """
    try:
        master = await resolve_admission_master(slug)
    except AdmissionUnavailable as unavailable:
        logger.warning(_RELEASE_UNANSWERED_EVENT, slug=slug, session_id=session_id, reason=unavailable.reason.value)
        return
    if master is None:
        await clear_matching_claim(project_root, slug, session_id)
        return
    body = (
        DriverReleaseRequest(project_path=project_identity_for_folder(project_root), slug=slug, session_id=session_id)
        .model_dump_json()
        .encode()
    )
    try:
        response = await _post_to_master(master, slug, RELEASE_PATH, body, caller, RELEASE_RELAY_DEADLINE_S)
    except AdmissionUnavailable as unavailable:
        logger.warning(_RELEASE_UNANSWERED_EVENT, slug=slug, session_id=session_id, reason=unavailable.reason.value)
        return
    if response.status_code != _HTTP_OK:
        logger.warning(_RELEASE_UNANSWERED_EVENT, slug=slug, session_id=session_id, status=response.status_code)


async def _release_in_own_section(project_root: Path, slug: str, session_id: str, caller: AdmissionCaller) -> None:
    try:
        async with driver_start_section(project_root, slug, starting_session_id=None):
            await _release_within_section(project_root, slug, session_id, caller)
    except DriverStartBusy:
        logger.info(_RELEASE_SKIPPED_EVENT, slug=slug, session_id=session_id)


def schedule_claim_release(
    project_root: Path, slug: str, session_id: str, caller: AdmissionCaller = AdmissionCaller()
) -> None:
    """Ask the master to release the claim naming ``session_id`` on ``slug``, without blocking the caller.

    The request is issued by a task that holds this computer's section for the todo until the master has
    answered or the relay deadline has passed, so no later start of the todo on this computer is admitted
    before the master has received this release, and a start of the todo meanwhile is refused at once as
    busy. A todo whose section is busy is skipped and left to the master's reconciliation.
    """
    spawn_tracked(_release_in_own_section(project_root, slug, session_id, caller))


async def _admit_within_section(request: StartRequest) -> None:
    """Decide the start: this computer's own holders first, then the master's admission."""
    root, slug = request.project_root, request.slug
    holder = await recheck_slug_holder(
        await get_db(), await get_workflow_store(root), root, slug, exempt_session_id=request.session_id
    )
    if holder is not None:
        raise ClaimConflict(slug=slug, holder=holder, computer=config.computer.name)
    master = await resolve_admission_master(slug)
    if master is None:
        await decide_driver_admission(request)
        return
    await _request_admission(master, request)
    await refresh_github_workflow_store(root, computer=config.computer.name)


def _refuse_waiter(decided: asyncio.Future[None], state: _StartState, refusal: OperationFailure) -> None:
    """Hand a refusal to the caller still waiting for the start's outcome; a caller that left learns nothing."""
    if state.waiting and not decided.done():
        decided.set_exception(refusal)


async def _run_start(
    request: StartRequest, state: _StartState, decided: asyncio.Future[None], finished: asyncio.Future[bool]
) -> None:
    """Own the todo's section on this computer from the start's admission until its caller has finished creating.

    A start that is refused nothing was recorded for. A start whose outcome is unknown (the master could not
    be reached or did not answer), whose caller stopped waiting, or whose creation failed asks the master to
    release the claim named for its session, still inside the section, so a release always reaches the
    master before any later start of the todo from this computer.
    """
    try:
        async with driver_start_section(request.project_root, request.slug, starting_session_id=request.session_id):
            try:
                await _admit_within_section(request)
            except (ClaimConflict, DriverStartBusy) as refusal:
                _refuse_waiter(decided, state, refusal)
                return
            except AdmissionUnavailable as unavailable:
                await _release_within_section(request.project_root, request.slug, request.session_id, request.caller)
                _refuse_waiter(decided, state, unavailable)
                return
            except Exception as error:  # supervision boundary of the start task: contain the failure, then withdraw
                logger.exception(_START_FAILED_EVENT, slug=request.slug, session_id=request.session_id)
                await _release_within_section(request.project_root, request.slug, request.session_id, request.caller)
                failure = AdmissionUnavailable(
                    slug=request.slug, reason=AdmissionUnavailableReason.ADMISSION_FAILED, detail=str(error)
                )
                _refuse_waiter(decided, state, failure)
                return
            created = False
            if state.waiting:
                decided.set_result(None)
                created = await finished
            if not created:
                logger.info(_START_RELEASED_EVENT, slug=request.slug, session_id=request.session_id)
                await _release_within_section(request.project_root, request.slug, request.session_id, request.caller)
    except DriverStartBusy as busy:
        _refuse_waiter(decided, state, busy)


@asynccontextmanager
async def admitted_start(request: StartRequest) -> AsyncIterator[None]:
    """Hold this computer's section for a GitHub-backed start while the master admits it and the caller creates.

    The start runs as a task that owns the todo's section on this computer; the caller waits for its
    outcome only up to :data:`START_BUDGET_S`. Entering returns once the master has recorded the claim, or
    raises the refusal: :class:`ClaimConflict` naming the holder and its computer, :class:`DriverStartBusy`,
    or :class:`AdmissionUnavailable` (also when the budget expires first, in which case the task finishes
    on its own and withdraws a claim it recorded). The caller creates its session or reflects its adoption
    inside the context; leaving it with an error withdraws the claim, leaving it cleanly ends the section.
    """
    loop = asyncio.get_running_loop()
    decided: asyncio.Future[None] = loop.create_future()
    finished: asyncio.Future[bool] = loop.create_future()
    state = _StartState()
    spawn_tracked(_run_start(request, state, decided, finished))
    try:
        await asyncio.wait_for(asyncio.shield(decided), START_BUDGET_S)
    except TimeoutError as error:
        state.waiting = False
        _finish(finished, created=False)
        raise AdmissionUnavailable(
            slug=request.slug, reason=AdmissionUnavailableReason.UNDECIDED_WITHIN_BUDGET
        ) from error
    except BaseException:
        state.waiting = False
        _finish(finished, created=False)
        raise
    try:
        yield
    except BaseException:
        _finish(finished, created=False)
        raise
    _finish(finished, created=True)


def _finish(finished: asyncio.Future[bool], *, created: bool) -> None:
    if not finished.done():
        finished.set_result(created)


def admission_conflict_detail(conflict: ClaimConflict) -> str:
    """The create door's 409 detail for a held GitHub-backed todo: a declared kind, the holder and its computer.

    The kind is distinct from every other 409 of the create door, so the runner reads the refusal by its
    declared kind and never by its prose.
    """
    payload: dict[str, object] = dict(conflict.to_error_payload())  # guard: loose-dict - declared wire payload
    payload[_KIND_FIELD] = ADMISSION_CONFLICT_KIND
    payload[_SUMMARY_FIELD] = conflict.summary()
    return json.dumps(payload)


def parse_admission_conflict(slug: str, detail: str | None) -> ClaimConflict | None:
    """Rebuild the :class:`ClaimConflict` a create door's admission refusal declared; ``None`` for any other 409."""
    if not detail:
        return None
    try:
        payload: object = json.loads(detail)
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get(_KIND_FIELD) != ADMISSION_CONFLICT_KIND:
        return None
    return ClaimConflict.from_error_payload(slug, {str(key): value for key, value in payload.items()})
