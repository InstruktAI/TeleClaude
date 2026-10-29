"""Continuity of a person's Discord messages across a daemon restart.

A person talks to a session through its thread in a project forum or through their Team channel; each such
channel is a place. This module owns what keeps those messages from being lost
(``local/projects/teleclaude/spec/feature/integration/discord-message-continuity``):

* the per-place ordered handoff: every managed-place input, live or recovered, is handled after the one before
  it in the same place has concluded, and a place's cursor moves to a message only when its handling concluded;
  a message the draining daemon refused has not concluded, so its place is held for the rest of the process and
  the recovery after the restart hands the message and everything after it on;
* the live gate: a place's live input waits while that place's history is being recovered;
* recovery passes: after each new gateway session, and after each later publication of routing, the history of
  every place bound to a still-active session is read after its cursor and handed to the same handling a live
  message takes.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Final, Protocol, cast

from instrukt_ai_logging import get_logger

from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.core.dates import parse_iso_datetime
from teleclaude.core.db._conversation_bindings import ConversationBinding
from teleclaude.core.db._discord_inbound_cursors import DiscordThreadPlace
from teleclaude.core.inbound.models import DISCORD_DM_KEY_FIELD
from teleclaude.core.integration.discord_inbound_cursor import EMPTY_PLACE_CURSOR, seed_for_place
from teleclaude.core.models import Session
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_idle_compaction import live_idle_close
from teleclaude.core.session_status import is_session_terminal
from teleclaude.core.shutdown_drain import ShutdownRefusal

if TYPE_CHECKING:
    from types import ModuleType

    from teleclaude.core.task_registry import TaskRegistry

logger = get_logger(__name__)

_ID_ATTR: Final = "id"
_GUILD_ATTR: Final = "guild"
_CHANNEL_ATTR: Final = "channel"
_CREATED_AT_ATTR: Final = "created_at"
_HISTORY_ATTR: Final = "history"
_OBJECT_ATTR: Final = "Object"
_NOT_FOUND_ATTR: Final = "NotFound"
_GET_CHANNEL_ATTR: Final = "get_channel"
_FETCH_CHANNEL_ATTR: Final = "fetch_channel"
_RECOVERY_TASK_NAME: Final = "discord-inbound-recovery"
_ENUMERATION_TASK_NAME: Final = "discord-inbound-enumeration"
_HANDOFF_TASK_NAME_TEMPLATE: Final = "discord-place-{place_id}-{message_id}"
_HISTORY_UNAVAILABLE_TEMPLATE: Final = "Discord channel {place_id} has no readable history"

_ENUMERATION_FAILED_EVENT: Final = "discord_recovery_enumeration_failed"
_PLACE_RECOVERED_EVENT: Final = "discord_place_recovered"
_PLACE_SKIPPED_EVENT: Final = "discord_place_recovery_skipped"
_PLACE_FAILED_EVENT: Final = "discord_place_recovery_failed"
_RECOVERY_COMPLETED_EVENT: Final = "discord_recovery_completed"
_HANDLING_FAILED_EVENT: Final = "discord_place_input_handling_failed"
_CURSOR_NOT_STARTED_EVENT: Final = "discord_cursor_not_started"

# A place whose history could not be read is retried with a growing pause, up to a ceiling.
_RETRY_INITIAL_DELAY_S: Final = 2.0
_RETRY_MAX_DELAY_S: Final = 60.0
_RETRY_GROWTH: Final = 2.0


class ContinuityStore(Protocol):
    """The storage the continuity needs: its cursors, and the durable bindings it recovers from."""

    async def get_discord_inbound_cursor(self, place_id: int) -> int | None: ...

    async def create_discord_inbound_cursor(self, place_id: int, message_id: int) -> bool: ...

    async def advance_discord_inbound_cursor(self, place_id: int, message_id: int) -> None: ...

    async def list_active_discord_threads(self) -> list[DiscordThreadPlace]: ...

    async def newest_retained_discord_input(self, session_ids: Sequence[str]) -> int | None: ...

    async def get_conversation_binding(
        self, origin: str, key_field: str, conversation_key: str
    ) -> ConversationBinding | None: ...

    async def get_session(self, session_id: str) -> Session | None: ...


class ContinuityHost(Protocol):
    """What the continuity needs from the Discord adapter that owns it."""

    task_registry: TaskRegistry
    _discord: ModuleType
    _guild_id: int | None
    _forum_routing_ready: asyncio.Event
    _team_channel_map: dict[int, str]

    @property
    def _client(self) -> object | None: ...

    def _is_managed_channel(self, channel: object) -> bool: ...

    def _is_bot_message(self, message: object) -> bool: ...

    async def _handle_managed_message(self, message: object, recovered_at: datetime | None) -> None: ...


def _snowflake(value: object) -> int | None:
    """A Discord id as the integer the SDK reports it as."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


class _RecoveryOutcome(StrEnum):
    RECOVERED = "recovered"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class _PlaceRecovery:
    """How one place's recovery ended, and how many messages it handed on."""

    outcome: _RecoveryOutcome
    handed: int = 0


@dataclass(frozen=True)
class RecoveryPlace:
    """A place bound to still-active sessions, as the durable bindings name it."""

    place_id: int
    session_ids: tuple[str, ...]
    bound_at: datetime | None


def session_serves_input(session: Session) -> bool:
    """Whether a session is open, or closed only by the idle cycle and resumed by the next input."""
    return not is_session_terminal(lifecycle_status=session.lifecycle_status, closed_at=session.closed_at) or (
        live_idle_close(session)
    )


@dataclass(frozen=True)
class InputRefused:
    """What spawned input work returns when the daemon refused it because it is draining.

    A returned outcome, not a raised error: the task registry reports every raising task as a failure, and a
    drain refusal is no failure of the work.
    """

    refusal: ShutdownRefusal


async def report_refusal_of[T](work: Awaitable[T]) -> T | InputRefused:
    """Await input work, reporting a draining refusal as the work's outcome instead of answering it to the sender."""
    try:
        return await work
    except ShutdownRefusal as refusal:
        return InputRefused(refusal)


async def await_conclusion(tasks: Iterable[asyncio.Task[object] | None]) -> None:
    """Wait for spawned input work to end, however it ends, and refuse to call it concluded if it did not.

    A failure of the work is reported by the task registry as it is for any background work; here it only ends
    the wait. Work cancelled by a shutdown has not concluded, so the cursor must not pass it, and neither has work
    the draining daemon refused: that raises the refusal.
    """
    spawned = {task for task in tasks if task is not None}
    if not spawned:
        return
    done, _ = await asyncio.wait(spawned)
    if any(task.cancelled() for task in done):
        raise asyncio.CancelledError
    for task in done:
        if task.exception() is None:
            outcome = task.result()
            if isinstance(outcome, InputRefused):
                raise outcome.refusal


class InboundContinuity:
    """Orders, gates and recovers the inbound messages of the places a daemon restart could cost."""

    def __init__(self, host: ContinuityHost, store: ContinuityStore) -> None:
        self._host = host
        self._store = store
        self._locks: dict[int, asyncio.Lock] = {}
        self._queued: dict[int, set[int]] = {}
        self._pending: dict[int, RecoveryPlace] = {}
        self._recovered: set[int] = set()
        self._failing: set[int] = set()
        self._held: set[int] = set()
        self._epoch = 0
        self._request_serial = 0
        self._enumerated_serial = 0
        self._enumerated = host._guild_id is None
        self._enumerator: asyncio.Task[None] | None = None
        self._recoverer: asyncio.Task[None] | None = None
        self._request_event = asyncio.Event()
        self._released = asyncio.Condition()

    # ------------------------------------------------------------------ live gate and ordered handoff

    async def hand_off_live(self, message: object) -> None:
        """Hand a managed live message on once its place is recovered, behind everything posted before it."""
        place_id = _snowflake(getattr(getattr(message, _CHANNEL_ATTR, None), _ID_ATTR, None))
        message_id = _snowflake(getattr(message, _ID_ATTR, None))
        if place_id is None or message_id is None:
            await self._host._handle_managed_message(message, None)
            return
        async with self._released:
            await self._released.wait_for(lambda: self._enumerated and place_id not in self._pending)
        self._hand_off(place_id, message_id, message, None)

    def _hand_off(self, place_id: int, message_id: int, message: object, recovered_at: datetime | None) -> None:
        """Queue one message behind its place's earlier input; a message already queued or in handling is not queued again."""
        queued = self._queued.setdefault(place_id, set())
        if message_id in queued:
            return
        queued.add(message_id)
        self._host.task_registry.spawn(
            self._handle_in_order(place_id, message_id, message, recovered_at),
            name=_HANDOFF_TASK_NAME_TEMPLATE.format(place_id=place_id, message_id=message_id),
        )

    async def _handle_in_order(
        self, place_id: int, message_id: int, message: object, recovered_at: datetime | None
    ) -> None:
        """Handle one message once the one before it has concluded, then move the place's cursor to it.

        A message the draining daemon refused has not concluded: the cursor stays before it and the place is held,
        so nothing after it is handled or moves the cursor past it. Admission never reopens within a process, so the
        hold is never lifted; the recovery after the restart hands the refused message and its successors on.
        """
        lock = self._locks.setdefault(place_id, asyncio.Lock())
        try:
            async with lock:
                if place_id in self._held:
                    return
                cursor = await self._store.get_discord_inbound_cursor(place_id)
                if cursor is not None and message_id <= cursor:
                    return
                try:
                    await self._host._handle_managed_message(message, recovered_at)
                except ShutdownRefusal:
                    self._held.add(place_id)
                    logger.info("discord_place_input_retained_for_recovery", place_id=place_id, message_id=message_id)
                    return
                except Exception:
                    # A failure of the handling is its definitive end; the handling reports it as it always has.
                    logger.error(_HANDLING_FAILED_EVENT, place_id=place_id, message_id=message_id, exc_info=True)
                await self._store.advance_discord_inbound_cursor(place_id, message_id)
        finally:
            self._queued[place_id].discard(message_id)

    # ------------------------------------------------------------------ cursor creation

    async def start_cursor(self, place_id: int, message_id: int) -> None:
        """Start the cursor of a place that has just become bound, at its newest message."""
        try:
            await self._store.create_discord_inbound_cursor(place_id, message_id)
        # The cursor is a safeguard: a recovery pass starts any place found without one, so failing to
        # start it here must not fail the binding it accompanies.
        except Exception:
            logger.warning(_CURSOR_NOT_STARTED_EVENT, place_id=place_id, exc_info=True)

    async def start_cursor_at_newest(self, place_id: int) -> None:
        """Start the cursor of a place that has just become bound, at the newest message it holds."""
        if await self._store.get_discord_inbound_cursor(place_id) is not None:
            return
        try:
            channel = await self._resolve_channel(place_id)
            newest = await self._newest_message_id(channel) if channel is not None else None
        except Exception:
            logger.warning(_CURSOR_NOT_STARTED_EVENT, place_id=place_id, exc_info=True)
            return
        if newest is not None:
            await self.start_cursor(place_id, newest)

    # ------------------------------------------------------------------ recovery passes

    def begin_gateway_session(self) -> None:
        """A new gateway session has started: nothing it carries is known to cover what was posted before it.

        Everything waits for the recovery pass that follows, and every place is recovered again in this session.
        """
        if self._host._guild_id is None:
            return
        self._epoch += 1
        self._recovered.clear()
        self._enumerated = False

    def request_recovery(self) -> None:
        """Ask for a recovery pass: routing was established, or a new gateway session has been prepared.

        Input of every place waits until the places the pass must recover have been named.
        """
        if self._host._guild_id is None:
            return
        self._request_serial += 1
        self._enumerated = False
        self._request_event.set()
        if self._enumerator is None or self._enumerator.done():
            self._enumerator = self._host.task_registry.spawn(self._enumerate(), name=_ENUMERATION_TASK_NAME)

    async def _enumerate(self) -> None:
        """Name the places to recover, from the durable bindings rather than from the routing maps.

        Input stays held until the places have been named. A lookup that fails names nothing, so it is retried
        with a growing pause and the hold stays: an unknown scope is never taken for an empty one.
        """
        delay = _RETRY_INITIAL_DELAY_S
        while True:
            while self._enumerated_serial != self._request_serial:
                serial = self._request_serial
                try:
                    places = await self._eligible_places()
                # The supervision boundary of the lookup: its failure is reported and retried, never certified.
                except Exception:
                    if delay == _RETRY_INITIAL_DELAY_S:
                        logger.error(_ENUMERATION_FAILED_EVENT, exc_info=True)
                    else:
                        logger.debug(_ENUMERATION_FAILED_EVENT, exc_info=True)
                    await asyncio.sleep(delay)
                    delay = min(delay * _RETRY_GROWTH, _RETRY_MAX_DELAY_S)
                    continue
                delay = _RETRY_INITIAL_DELAY_S
                for place in places:
                    if place.place_id not in self._recovered:
                        self._pending[place.place_id] = place
                self._enumerated_serial = serial
            self._enumerated = True
            await self._notify_released()
            if self._enumerated_serial == self._request_serial:
                break
        if self._pending and (self._recoverer is None or self._recoverer.done()):
            self._recoverer = self._host.task_registry.spawn(self._recover_pending(), name=_RECOVERY_TASK_NAME)

    async def _eligible_places(self) -> list[RecoveryPlace]:
        """Every thread and Team channel bound to a session that is still active.

        A binding or session that cannot be read fails the whole lookup, which is retried.
        """
        places = [
            RecoveryPlace(place_id=thread.thread_id, session_ids=thread.session_ids, bound_at=thread.bound_at)
            for thread in await self._store.list_active_discord_threads()
        ]
        for channel_id in tuple(self._host._team_channel_map):
            binding = await self._store.get_conversation_binding(
                InputOrigin.DISCORD.value, DISCORD_DM_KEY_FIELD, str(channel_id)
            )
            if binding is None:
                continue
            session = await self._store.get_session(binding.session_id)
            if session is not None and not session_serves_input(session):
                continue
            places.append(
                RecoveryPlace(
                    place_id=channel_id,
                    session_ids=(binding.session_id,),
                    bound_at=parse_iso_datetime(binding.entered_at),
                )
            )
        return places

    async def _recover_pending(self) -> None:
        """Recover every pending place once routing has been attempted, retrying the ones whose history failed."""
        await self._host._forum_routing_ready.wait()
        delay = _RETRY_INITIAL_DELAY_S
        recovered_places = 0
        handed_messages = 0
        while self._pending:
            failed = False
            for place in tuple(self._pending.values()):
                epoch = self._epoch
                recovery = await self._recover_place(place)
                if recovery.outcome is _RecoveryOutcome.FAILED:
                    failed = True
                    continue
                if recovery.outcome is _RecoveryOutcome.RECOVERED and epoch != self._epoch:
                    # A new gateway session began while the place was read: it is read again in that session.
                    continue
                self._pending.pop(place.place_id, None)
                if recovery.outcome is _RecoveryOutcome.RECOVERED:
                    self._recovered.add(place.place_id)
                    recovered_places += 1
                    handed_messages += recovery.handed
                await self._notify_released()
            if not failed:
                delay = _RETRY_INITIAL_DELAY_S
                continue
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._request_event.wait(), timeout=delay)
            self._request_event.clear()
            delay = min(delay * _RETRY_GROWTH, _RETRY_MAX_DELAY_S)
        logger.info(_RECOVERY_COMPLETED_EVENT, places=recovered_places, messages=handed_messages)

    async def _recover_place(self, place: RecoveryPlace) -> _PlaceRecovery:
        """Read a place's history after its cursor to the end, handing each human message to the ordered handoff."""
        place_id = place.place_id
        try:
            channel = await self._resolve_channel(place_id)
            if channel is None or not self._host._is_managed_channel(channel):
                logger.debug(_PLACE_SKIPPED_EVENT, place_id=place_id)
                return _PlaceRecovery(_RecoveryOutcome.SKIPPED)
            cursor = await self._store.get_discord_inbound_cursor(place_id)
            if cursor is None:
                cursor = await self._start_unseeded_cursor(place)
            handed = 0
            async for message in self._history_after(channel, place_id, cursor):
                handed += self._hand_off_recovered(place_id, message)
        # The supervision boundary of one place: its failure leaves it pending for a retry and never
        # stops the recovery of the others. A place that keeps failing is reported once, not at every retry.
        except Exception:
            if place_id in self._failing:
                logger.debug(_PLACE_FAILED_EVENT, place_id=place_id, exc_info=True)
            else:
                self._failing.add(place_id)
                logger.error(_PLACE_FAILED_EVENT, place_id=place_id, exc_info=True)
            return _PlaceRecovery(_RecoveryOutcome.FAILED)
        self._failing.discard(place_id)
        logger.debug(_PLACE_RECOVERED_EVENT, place_id=place_id, handed=handed)
        return _PlaceRecovery(_RecoveryOutcome.RECOVERED, handed)

    def _hand_off_recovered(self, place_id: int, message: object) -> int:
        """Hand a recovered human message from this guild to the ordered handoff; the number handed on (0 or 1)."""
        host = self._host
        message_id = _snowflake(getattr(message, _ID_ATTR, None))
        guild_id = _snowflake(getattr(getattr(message, _GUILD_ATTR, None), _ID_ATTR, None))
        if message_id is None or host._is_bot_message(message) or guild_id != host._guild_id:
            return 0
        posted_at = getattr(message, _CREATED_AT_ATTR, None)
        self._hand_off(
            place_id, message_id, message, posted_at if isinstance(posted_at, datetime) else datetime.now(UTC)
        )
        return 1

    async def _start_unseeded_cursor(self, place: RecoveryPlace) -> int:
        """Start the cursor of a place found without one, by the installation rule, never before it was bound."""
        newest = await self._store.newest_retained_discord_input(place.session_ids)
        seed = seed_for_place(newest, bound_at=place.bound_at, now=datetime.now(UTC))
        await self._store.create_discord_inbound_cursor(place.place_id, seed)
        return await self._store.get_discord_inbound_cursor(place.place_id) or seed

    def _history_after(self, channel: object, place_id: int, cursor: int) -> AsyncIterator[object]:
        """A place's messages after ``cursor``, oldest first, with no limit: the SDK default would truncate."""
        history = getattr(channel, _HISTORY_ATTR, None)
        object_type = getattr(self._host._discord, _OBJECT_ATTR, None)
        if not callable(history) or not callable(object_type):
            raise AdapterError(_HISTORY_UNAVAILABLE_TEMPLATE.format(place_id=place_id))
        return cast(AsyncIterator[object], history(limit=None, after=object_type(id=cursor), oldest_first=True))

    async def _newest_message_id(self, channel: object) -> int:
        """The newest message a channel holds, or the beginning of an empty one."""
        history = getattr(channel, _HISTORY_ATTR, None)
        if not callable(history):
            return EMPTY_PLACE_CURSOR
        newest = cast(AsyncIterator[object], history(limit=1))
        async for message in newest:
            return _snowflake(getattr(message, _ID_ATTR, None)) or EMPTY_PLACE_CURSOR
        return EMPTY_PLACE_CURSOR

    async def _resolve_channel(self, channel_id: int) -> object | None:
        """The channel from the SDK cache or the API; ``None`` only when Discord says it no longer exists.

        Any other failure to resolve it raises, so a place is never taken for gone because Discord was unreachable.
        """
        client = self._host._client
        get_channel = getattr(client, _GET_CHANNEL_ATTR, None)
        cached: object | None = get_channel(channel_id) if callable(get_channel) else None
        if cached is not None:
            return cached
        fetch_channel = cast(Callable[[int], Awaitable[object]] | None, getattr(client, _FETCH_CHANNEL_ATTR, None))
        if fetch_channel is None:
            return None
        try:
            return await fetch_channel(channel_id)
        except self._not_found_errors() as exc:
            logger.debug(_PLACE_SKIPPED_EVENT, place_id=channel_id, reason=type(exc).__name__)
            return None

    def _not_found_errors(self) -> tuple[type[Exception], ...]:
        """The exception type Discord raises for a channel that no longer exists."""
        not_found = getattr(self._host._discord, _NOT_FOUND_ATTR, None)
        return (not_found,) if isinstance(not_found, type) and issubclass(not_found, Exception) else ()

    async def _notify_released(self) -> None:
        """Wake the live input that waits for a place to be recovered."""
        async with self._released:
            self._released.notify_all()
