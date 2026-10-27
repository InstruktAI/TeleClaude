"""Write the fleet's captured turns to GitHub, from the one computer that sends conversation requests.

The master alone sends, so recovery and admission live here, where the requests are made. A hand-over carries the
comments of one turn still to be written. The master admits each request under the fleet's budget, writes the
comments in order as the App chosen for the session, and answers how many of them are now on GitHub: all of them,
some before the budget or GitHub asked it to wait, or none because it was refused, with the cause.

When the sender says an earlier hand-over may have written part of the turn, the master first reads the
destination's comments by that App and takes each comment whose envelope names the session, the turn and the part
as already written, so a lost reply or a restart never writes a comment twice.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Final

from instrukt_ai_logging import get_logger

from teleclaude.config.machine import config
from teleclaude.core.workflow_store.github_conversation_budget import ConversationBudget
from teleclaude.core.workflow_store.github_conversation_io import (
    ConversationCommentPage,
    GitHubConversationIO,
    conversation_assignment_for_app,
)
from teleclaude.core.workflow_store.github_conversation_record import TurnEnvelope, parse_turn_envelope
from teleclaude.core.workflow_store.github_conversation_wire import (
    Destination,
    LimitNoticeRequest,
    LimitNoticeResponse,
    Outcome,
    PositionRequest,
    PositionResponse,
    PositionTurn,
    PostTurnRequest,
    PostTurnResponse,
    RefusalCause,
)
from teleclaude.core.workflow_store.github_io_models import GitHubRepositoryScope
from teleclaude.core.workflow_store.github_io_transport import GitHubIOFailure, GitHubIORefused
from teleclaude.types.github_binding import GitHubActorAssignment

logger = get_logger(__name__)

_LATER: Final = timedelta(minutes=1)
_FIRST_PAGE: Final = 1
_POSTED_EVENT = "conversation_turn_posted"
_HALTED_EVENT = "conversation_request_halted"
_CAUSES: Final = {
    GitHubIOFailure.ROLE_UNMAPPED: RefusalCause.ROLE_UNMAPPED,
    GitHubIOFailure.CREDENTIAL_REFUSED: RefusalCause.CREDENTIAL_REFUSED,
    GitHubIOFailure.VALIDATION_REFUSED: RefusalCause.VALIDATION_REFUSED,
    GitHubIOFailure.NOT_FOUND: RefusalCause.NOT_FOUND,
}
_WAIT_FAILURES: Final = frozenset({GitHubIOFailure.RATE_LIMITED, GitHubIOFailure.UNAVAILABLE})

type IOFactory = Callable[[GitHubRepositoryScope], GitHubConversationIO]


@dataclass(frozen=True)
class _Halt:
    """Why a request stopped before it was done: the sender should wait until a time, or the request was refused."""

    outcome: Outcome
    retry_at: datetime | None = None
    cause: RefusalCause | None = None
    uncertain: bool = False


def _halt_for(error: GitHubIORefused, *, creating: bool = False) -> _Halt:
    """The halt a refusal means. A failed create that is not a definite answer may still have been applied."""
    if error.reason in _WAIT_FAILURES:
        return _Halt(
            Outcome.DEFERRED,
            retry_at=datetime.now(UTC) + _LATER,
            uncertain=creating and error.reason is GitHubIOFailure.UNAVAILABLE,
        )
    return _Halt(Outcome.REFUSED, cause=_CAUSES.get(error.reason, RefusalCause.UNAVAILABLE))


def _part_of(body: str) -> int | None:
    envelope = parse_turn_envelope(body)
    return envelope.part if envelope is not None else None


class GitHubConversationPoster:
    """The fleet master's poster: it implements what every computer's conversation requests ask of the master."""

    def __init__(
        self,
        budget: ConversationBudget,
        *,
        is_master: Callable[[], bool] = lambda: bool(config.computer.is_master),
        io_factory: IOFactory = GitHubConversationIO,
    ) -> None:
        self._budget = budget
        self._is_master = is_master
        self._io_factory = io_factory
        self._ios: dict[tuple[int, str], GitHubConversationIO] = {}
        self._append_lock = asyncio.Lock()

    async def post_turn(self, request: PostTurnRequest) -> PostTurnResponse:
        """Write the comments of a captured turn, in order, or say how far it got and why it stopped."""
        try:
            assignment = await conversation_assignment_for_app(request.app_id)
        except GitHubIORefused as error:
            return _post_response(_halt_for(error), written=0, still_unreconciled=request.possibly_sent)
        destination = request.destination
        present: frozenset[int] = frozenset()
        if request.possibly_sent:
            envelopes = await self._read_envelopes(assignment, destination, request.session_id)
            if isinstance(envelopes, _Halt):
                return _post_response(envelopes, written=0, still_unreconciled=True)
            present = frozenset(envelope.part for envelope in envelopes if envelope.ordinal == request.ordinal)
        written = 0
        for body in request.bodies:
            if _part_of(body) in present:
                written += 1
                continue
            halted = await self._create_comment(assignment, destination, body)
            if halted is not None:
                return _post_response(halted, written=written)
            written += 1
        logger.info(_POSTED_EVENT, session_id=request.session_id, ordinal=request.ordinal, comments=written)
        return PostTurnResponse(outcome=Outcome.OK, written=written)

    async def position(self, request: PositionRequest) -> PositionResponse:
        """Report which turns of a session the destination holds, and which of their comments."""
        try:
            assignment = await conversation_assignment_for_app(request.app_id)
        except GitHubIORefused as error:
            halted = _halt_for(error)
            return PositionResponse(outcome=halted.outcome, retry_at=halted.retry_at, cause=halted.cause)
        envelopes = await self._read_envelopes(assignment, request.destination, request.session_id)
        if isinstance(envelopes, _Halt):
            return PositionResponse(outcome=envelopes.outcome, retry_at=envelopes.retry_at, cause=envelopes.cause)
        parts: dict[int, int] = {}
        present: dict[int, set[int]] = {}
        for envelope in envelopes:
            parts[envelope.ordinal] = max(parts.get(envelope.ordinal, 0), envelope.parts)
            present.setdefault(envelope.ordinal, set()).add(envelope.part)
        return PositionResponse(
            outcome=Outcome.OK,
            turns=[
                PositionTurn(ordinal=ordinal, parts=parts[ordinal], present_parts=sorted(present[ordinal]))
                for ordinal in sorted(parts)
            ],
        )

    async def report_limit(self, request: LimitNoticeRequest) -> LimitNoticeResponse:
        """Pause the conversation after a limit response any computer received."""
        return LimitNoticeResponse(paused_until=await self._budget.note_limit(request.resume_at))

    def _io_for(self, destination: Destination) -> GitHubConversationIO:
        key = (destination.repository_id, destination.repository)
        io = self._ios.get(key)
        if io is None:
            io = self._io_factory(GitHubRepositoryScope(destination.repository_id, destination.repository))
            self._ios[key] = io
        return io

    async def _admitted(self, app_id: int, destination: Destination, *, creates: bool) -> _Halt | None:
        """None when one request may be sent; otherwise the halt that tells the sender when to try again."""
        admission = await self._budget.admit(
            app_id=app_id, repository=destination.repository, is_master=self._is_master(), creates=creates
        )
        if admission.admitted:
            return None
        if admission.retry_at is None:
            return _Halt(Outcome.REFUSED, cause=RefusalCause.NOT_MASTER)
        return _Halt(Outcome.DEFERRED, retry_at=admission.retry_at)

    async def _create_comment(
        self, assignment: GitHubActorAssignment, destination: Destination, body: str
    ) -> _Halt | None:
        # Admission reads the count of appends sent, so the decision, the append and its count are one unit: two
        # callers must never both take the last slot of a window.
        async with self._append_lock:
            halted = await self._admitted(assignment.app_id, destination, creates=True)
            if halted is not None:
                logger.info(_HALTED_EVENT, outcome=halted.outcome, cause=halted.cause)
                return halted
            io = self._io_for(destination)
            number = destination.number
            try:
                await asyncio.wrap_future(io.submit(partial(_create, assignment, number, body)))
            except GitHubIORefused as error:
                logger.warning(_HALTED_EVENT, reason=error.reason)
                return _halt_for(error, creating=True)
            await self._budget.record_send()
        return None

    async def _read_envelopes(
        self, assignment: GitHubActorAssignment, destination: Destination, session_id: str
    ) -> list[TurnEnvelope] | _Halt:
        """The turn envelopes of one session among the App's comments on the destination, or why reading stopped."""
        io = self._io_for(destination)
        number = destination.number
        found: list[TurnEnvelope] = []
        page = _FIRST_PAGE
        while True:
            halted = await self._admitted(assignment.app_id, destination, creates=False)
            if halted is not None:
                return halted
            try:
                listed = await asyncio.wrap_future(io.submit(partial(_read_page, assignment, number, page)))
            except GitHubIORefused as error:
                return _halt_for(error)
            for comment in listed.comments:
                envelope = parse_turn_envelope(comment.body)
                if envelope is not None and envelope.session_id == session_id:
                    found.append(envelope)
            if not listed.has_more:
                return found
            page += 1


async def _create(assignment: GitHubActorAssignment, number: int, body: str, io: GitHubConversationIO) -> int:
    return await io.create_comment(assignment, number, body)


async def _read_page(
    assignment: GitHubActorAssignment, number: int, page: int, io: GitHubConversationIO
) -> ConversationCommentPage:
    return await io.list_comments_page(assignment, number, page)


def _post_response(halted: _Halt, *, written: int, still_unreconciled: bool = False) -> PostTurnResponse:
    """The answer to a halted hand-over. One that was asked to read the destination first and stopped before it
    had still not settled the earlier hand-over's effect, so the sender keeps its mark that the turn may be written."""
    return PostTurnResponse(
        outcome=halted.outcome,
        written=written,
        retry_at=halted.retry_at,
        cause=halted.cause,
        uncertain=halted.uncertain or still_unreconciled,
    )
