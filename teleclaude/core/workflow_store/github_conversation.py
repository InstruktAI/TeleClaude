"""Capture the completed turns of the sessions this computer hosts and hand them to the fleet master to post.

The capturer reads each eligible session's completed turns from the runtime, decides where each goes and as which
App, protects and splits it, and keeps it in the working copy until it is on GitHub. It never reads a native
transcript, a session row's output cursor or a GitHub token itself. A pass is idempotent and loses nothing when it
is interrupted: each pass takes every completed turn after the last one captured and hands over every captured turn
not yet on GitHub, so the agent-stop event that wakes it carries no content and its loss loses nothing.

A turn goes on the item's pull request when the item had an open pull request when the turn completed, otherwise on
its issue, and on each destination turns are handed over in completion order, one at a time, each after the previous
one was posted. A destination that cannot be written to holds behind its first unposted turn.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Final, cast

from instrukt_ai_logging import get_logger

from teleclaude.config.machine import config
from teleclaude.core.db import db
from teleclaude.core.models import Session
from teleclaude.core.roles import RoleName
from teleclaude.core.session_completed_turns import (
    CompletedTurn,
    PersonChannel,
    TurnInputKind,
    TurnInputPart,
    read_completed_turns,
)
from teleclaude.core.todos_db._github_conversation import (
    CapturedPart,
    CapturedTurn,
    ConversationBookkeeping,
    SessionPointer,
)
from teleclaude.core.todos_db._github_pull_requests import pull_request_open_at
from teleclaude.core.workflow_store.github_conversation_budget import MasterTenure
from teleclaude.core.workflow_store.github_conversation_io import conversation_assignment_for_role
from teleclaude.core.workflow_store.github_conversation_master import ConversationMasterLink, MasterUnreachable
from teleclaude.core.workflow_store.github_conversation_protection import ProtectedTexts, protect_texts
from teleclaude.core.workflow_store.github_conversation_record import (
    TurnBlock,
    TurnBlockKind,
    TurnState,
    render_turn_comments,
)
from teleclaude.core.workflow_store.github_conversation_wire import (
    Destination,
    Outcome,
    PositionRequest,
    PositionResponse,
    PostTurnRequest,
)
from teleclaude.core.workflow_store.github_io_transport import GitHubIORefused
from teleclaude.core.workflow_store.github_store import (
    ConversationItem,
    GitHubWorkflowStore,
    get_github_workflow_store,
    github_working_copy_paths,
    read_conversation_item,
)

logger = get_logger(__name__)

# The roles the workflow dispatches for an item. A session with no role, any other role or no working item is never
# published: a commit review belongs to the project's ledger rather than one item, and the integrator and
# coordinator work across items.
ELIGIBLE_ROLES: Final = frozenset(
    {
        RoleName.PREPARE_ORCHESTRATOR,
        RoleName.WORK_ORCHESTRATOR,
        RoleName.INTAKER,
        RoleName.ARCHITECT,
        RoleName.PLANNER,
        RoleName.PRD_REVIEWER,
        RoleName.ARCHITECTURE_REVIEWER,
        RoleName.PLAN_REVIEWER,
        RoleName.BUILD_REVIEWER,
        RoleName.BUILDER,
        RoleName.FINALIZER,
        RoleName.DIAGNOSER,
        RoleName.DRIFT_ANALYZER,
        RoleName.DEFERRER,
    }
)
_ELIGIBLE_ROLE_NAMES: Final = frozenset(role.value for role in ELIGIBLE_ROLES)
_REFUSED_BACKOFF: Final = timedelta(minutes=5)
_UNREACHABLE_BACKOFF: Final = timedelta(minutes=1)
_CAPTURE_FAILED_EVENT = "conversation_capture_failed"
_CAPTURE_HELD_EVENT = "conversation_capture_held"
_CAPTURED_EVENT = "conversation_turn_captured"
_UNAVAILABLE_EVENT = "conversation_turn_unavailable"
_HAND_OVER_HELD_EVENT = "conversation_hand_over_held"

type _DestinationKey = tuple[int, int]


class _CaptureHeld(Exception):
    """A session's capture cannot proceed now and is tried again on the next pass; it carries no content."""


@dataclass(frozen=True)
class _Target:
    """Where one session's turns go and under which identity."""

    session_id: str
    role: str
    project_root: Path
    item: ConversationItem
    started_at: datetime
    app_id: int
    bookkeeping: ConversationBookkeeping


class ConversationPublisher:
    """Capture this computer's sessions' turns and hand them to the fleet master, on agent stops and on a schedule."""

    def __init__(
        self,
        link: ConversationMasterLink,
        tenure: MasterTenure,
        deliver_notices: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._link = link
        self._tenure = tenure
        self._deliver_notices = deliver_notices
        self._pass_lock = asyncio.Lock()
        self._held_until: dict[_DestinationKey, datetime] = {}
        self._bookkeepings: dict[Path, ConversationBookkeeping] = {}

    async def on_agent_stop(self, session_id: str) -> None:
        """Capture the stopped session's new turns, then hand over what is captured."""
        async with self._pass_lock:
            session = await db.get_session(session_id)
            if session is not None and _is_eligible(session):
                await self._capture(session)
            await self._hand_over()

    async def run_full_pass(self) -> None:
        """Capture every eligible session this computer hosts, then hand over what is captured.

        The consumer's recovery operation, run at start and on reconnection, and the store's periodic refresh.
        """
        async with self._pass_lock:
            await self._tenure.since(is_master=bool(config.computer.is_master), now=datetime.now(UTC))
            if self._deliver_notices is not None:
                await self._deliver_notices()
            for session in await db.list_sessions_working_items(_ELIGIBLE_ROLE_NAMES):
                await self._capture(session)
            await self._hand_over()

    async def _capture(self, session: Session) -> None:
        try:
            await self._capture_session(session)
        except _CaptureHeld:
            logger.info(_CAPTURE_HELD_EVENT, session_id=session.session_id)
        except Exception:  # supervision boundary: one session's failure never stops the pass or touches the session
            logger.warning(_CAPTURE_FAILED_EVENT, session_id=session.session_id, exc_info=True)

    async def _capture_session(self, session: Session) -> None:
        target = await self._target(session)
        if target is None:
            return
        pointer = await asyncio.to_thread(target.bookkeeping.pointer, target.session_id)
        turns = await read_completed_turns(target.session_id, pointer.last_identity if pointer else None)
        if not turns:
            return
        now = datetime.now(UTC)
        eligible = [turn for turn in turns if _completed_after(turn, target.started_at, now)]
        on_github: dict[int, tuple[int, frozenset[int]]] = {}
        if pointer is None and eligible:
            on_github = await self._position(target)
        for turn in turns:
            if turn not in eligible:
                await self._pass_over(target, turn)
                continue
            held = on_github.get(turn.ordinal)
            if held is not None and len(held[1]) >= held[0]:
                await self._pass_over(target, turn)
                continue
            await self._capture_turn(target, turn, held[1] if held is not None else frozenset(), now)

    async def _target(self, session: Session) -> _Target | None:
        """Resolve where a session's turns go, or None when nothing of it is published."""
        if not _is_eligible(session) or not session.project_path or not session.working_slug:
            return None
        project_root = Path(session.project_path)
        item = await asyncio.to_thread(read_conversation_item, project_root, session.working_slug)
        if item is None:
            return None
        if item.pull_request_owed:
            raise _CaptureHeld
        store = cast(GitHubWorkflowStore, await get_github_workflow_store(project_root))
        started_at = await store.conversation_start()
        if started_at is None:
            return None
        role = RoleName(session.role)
        try:
            assignment = await conversation_assignment_for_role(role)
        except GitHubIORefused as error:
            logger.warning(_CAPTURE_HELD_EVENT, session_id=session.session_id, reason=error.reason)
            raise _CaptureHeld from None
        bookkeeping = self._bookkeeping_for(Path(store.db_path))
        return _Target(
            session_id=session.session_id,
            role=role.value,
            project_root=project_root,
            item=item,
            started_at=started_at,
            app_id=assignment.app_id,
            bookkeeping=bookkeeping,
        )

    def _bookkeeping_for(self, db_path: Path) -> ConversationBookkeeping:
        bookkeeping = self._bookkeepings.get(db_path)
        if bookkeeping is None:
            bookkeeping = ConversationBookkeeping(db_path)
            self._bookkeepings[db_path] = bookkeeping
        return bookkeeping

    async def _position(self, target: _Target) -> dict[int, tuple[int, frozenset[int]]]:
        """For a session this working copy has not seen, which of its turns the item's destinations already hold."""
        found: dict[int, tuple[int, frozenset[int]]] = {}
        numbers = (target.item.issue_number, *target.item.intervals)
        for number in dict.fromkeys(numbers):
            request = PositionRequest(
                destination=Destination(
                    repository_id=target.item.repository_id, repository=target.item.repository, number=number
                ),
                app_id=target.app_id,
                session_id=target.session_id,
            )
            try:
                response: PositionResponse = await self._link.position(request)
            except MasterUnreachable:
                raise _CaptureHeld from None
            if response.outcome is not Outcome.OK:
                raise _CaptureHeld
            for position in response.turns:
                parts, present = found.get(position.ordinal, (0, frozenset[int]()))
                found[position.ordinal] = (max(parts, position.parts), present | frozenset(position.present_parts))
        return found

    async def _pass_over(self, target: _Target, turn: CompletedTurn) -> None:
        """Move the session's pointer past a turn that is published already or never will be."""
        await asyncio.to_thread(
            target.bookkeeping.advance_pointer, target.session_id, SessionPointer(turn.identity, turn.ordinal)
        )

    async def _capture_turn(self, target: _Target, turn: CompletedTurn, present: frozenset[int], now: datetime) -> None:
        completed_at = turn.completed_at or now
        number = pull_request_open_at(target.item.intervals.items(), completed_at) or target.item.issue_number
        bodies = await self._bodies(target, turn, completed_at)
        if present >= frozenset(range(1, len(bodies) + 1)):
            await self._pass_over(target, turn)
            return
        captured = CapturedTurn(
            session_id=target.session_id,
            ordinal=turn.ordinal,
            turn_identity=turn.identity,
            item_id=target.item.item_id,
            repository_id=target.item.repository_id,
            repository=target.item.repository,
            destination_number=number,
            app_id=target.app_id,
            completed_at=completed_at,
            parts=tuple(CapturedPart(index, body, posted=index in present) for index, body in enumerate(bodies, 1)),
            in_flight=bool(present),
        )
        await asyncio.to_thread(target.bookkeeping.capture, captured, now)
        logger.info(_CAPTURED_EVENT, session_id=target.session_id, ordinal=turn.ordinal, comments=len(bodies))

    async def _bodies(self, target: _Target, turn: CompletedTurn, completed_at: datetime) -> list[str]:
        """The comments that carry a turn: its content protected, or only its envelope when it cannot be shown."""
        if turn.unreadable:
            logger.warning(_UNAVAILABLE_EVENT, session_id=target.session_id, ordinal=turn.ordinal)
            return list(self._render(target, turn, completed_at, TurnState.UNAVAILABLE, []))
        shown = [part for part in turn.input_parts if _is_shown(part)]
        protected = await asyncio.to_thread(
            protect_texts, [*(part.text for part in shown), turn.reply], target.project_root
        )
        if not isinstance(protected, ProtectedTexts):
            return list(self._render(target, turn, completed_at, TurnState.WITHHELD, []))
        texts = iter(protected.texts)
        blocks: list[TurnBlock] = []
        for part in turn.input_parts:
            blocks.append(_block(part, next(texts) if _is_shown(part) else ""))
        blocks.append(TurnBlock(TurnBlockKind.REPLY, next(texts)))
        return list(self._render(target, turn, completed_at, TurnState.COMPLETE, blocks))

    def _render(
        self, target: _Target, turn: CompletedTurn, completed_at: datetime, state: TurnState, blocks: list[TurnBlock]
    ) -> tuple[str, ...]:
        return render_turn_comments(target.session_id, target.role, turn.ordinal, completed_at, state, blocks)

    async def _hand_over(self) -> None:
        """Hand every captured turn not yet on GitHub to the master, per destination in completion order.

        Turns captured before a restart are found in the working copies of the registered GitHub projects, whatever
        the age of the sessions that captured them.
        """
        for path in await asyncio.to_thread(github_working_copy_paths):
            self._bookkeeping_for(path)
        for bookkeeping in tuple(self._bookkeepings.values()):
            turns = await asyncio.to_thread(bookkeeping.pending_turns)
            held: set[_DestinationKey] = set()
            for turn in turns:
                key = (turn.repository_id, turn.destination_number)
                if key in held or self._is_held(key):
                    continue
                if not await self._hand_over_turn(bookkeeping, turn):
                    held.add(key)

    def _is_held(self, key: _DestinationKey) -> bool:
        until = self._held_until.get(key)
        return until is not None and until > datetime.now(UTC)

    async def _hand_over_turn(self, bookkeeping: ConversationBookkeeping, turn: CapturedTurn) -> bool:
        """Hand one turn over; True when it is entirely on GitHub, False when its destination now holds."""
        key = (turn.repository_id, turn.destination_number)
        possibly_sent = await asyncio.to_thread(bookkeeping.begin_handover, turn.session_id, turn.ordinal)
        request = PostTurnRequest(
            destination=Destination(
                repository_id=turn.repository_id, repository=turn.repository, number=turn.destination_number
            ),
            app_id=turn.app_id,
            session_id=turn.session_id,
            ordinal=turn.ordinal,
            bodies=[part.body for part in turn.unposted],
            possibly_sent=possibly_sent,
        )
        try:
            response = await self._link.post_turn(request)
        except MasterUnreachable:
            self._held_until[key] = datetime.now(UTC) + _UNREACHABLE_BACKOFF
            return False
        done = await asyncio.to_thread(
            partial(
                bookkeeping.end_handover,
                turn.session_id,
                turn.ordinal,
                response.written,
                uncertain=response.uncertain,
            )
        )
        if response.outcome is Outcome.OK and done:
            return True
        backoff = _REFUSED_BACKOFF if response.outcome is Outcome.REFUSED else _UNREACHABLE_BACKOFF
        self._held_until[key] = response.retry_at or datetime.now(UTC) + backoff
        logger.info(_HAND_OVER_HELD_EVENT, outcome=response.outcome, cause=response.cause)
        return False


def _is_eligible(session: Session) -> bool:
    return session.role in _ELIGIBLE_ROLE_NAMES and bool(session.working_slug)


def _completed_after(turn: CompletedTurn, started_at: datetime, now: datetime) -> bool:
    """A turn belongs to the conversation when it completed at or after the project's conversation start."""
    return (turn.completed_at or now) >= started_at


def _is_shown(part: TurnInputPart) -> bool:
    """Whether a part's words are written: a person's words given anywhere but GitHub are not."""
    return not (part.kind is TurnInputKind.PERSON and part.channel is not PersonChannel.GITHUB)


def _block(part: TurnInputPart, text: str) -> TurnBlock:
    match part.kind:
        case TurnInputKind.PERSON if part.channel is PersonChannel.GITHUB:
            return TurnBlock(
                TurnBlockKind.GITHUB_PERSON, text, login=part.person_login or part.person_display, link=part.person_link
            )
        case TurnInputKind.PERSON:
            return TurnBlock(TurnBlockKind.PERSON_ELSEWHERE)
        case TurnInputKind.PEER:
            return TurnBlock(TurnBlockKind.PEER, text, peer_session_id=part.peer_session_id, peer_role=part.peer_role)
        case TurnInputKind.PLATFORM:
            return TurnBlock(TurnBlockKind.PLATFORM, text)
