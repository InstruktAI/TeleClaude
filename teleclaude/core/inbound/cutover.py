"""The cutover from per-computer handling to master routing, on adapters whose messages reach every computer.

Before the cutover every computer handles Discord direct messages and WhatsApp
on its own, as before shared routing existed. The cutover is one-way and runs
in three steps, so that no computer handles these conversations on its own
while the master routes them:

1. Activation. Once every expected source has answered the adoption run, the
   master records the activation and publishes it under a durable shared key.
2. Arming. Every computer that learns of the activation (from that key, or
   from any live computer announcing it) records it and stops admitting these
   conversations to its own handling. It announces that it has armed only once
   every message it had already admitted has finished, so an armed computer
   creates nothing on its own any more. A computer that was away learns it
   before it handles another message; one that cannot read the key and sees
   no armed computer cannot tell, and handles nothing on its own.
3. Changeover. The master starts routing only when every live computer
   receiving these conversations has armed. It then takes each one's export
   once more (no computer creates sessions on its own any more), binds every
   conversation to its newest open session, and records the start. Messages
   reaching the master meanwhile wait for the start instead of being handled
   twice; a computer that comes back later is exported once it has armed.
   While a computer named in the adoption run has not been exported at the
   changeover, a conversation with no binding may be one of its own, so the
   master starts no session for it by role.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import StrEnum
from typing import TYPE_CHECKING

from instrukt_ai_logging import get_logger

from teleclaude.config.machine import config
from teleclaude.core.db import Db
from teleclaude.core.inbound.adoption import run_adoption_pass, run_orphan_pass, seed_bindings
from teleclaude.core.origins import InputOrigin

if TYPE_CHECKING:
    from teleclaude.core.inbound.conversation_env import ConversationEnvironment
    from teleclaude.core.inbound.fleet import FleetMember, FleetView

logger = get_logger(__name__)

# The system setting recording when this computer armed: it no longer handles
# shared-adapter conversations on its own.
ROUTING_ACTIVATED_AT_SETTING = "conversation_routing_activated_at"
# The master's system setting recording when it started routing.
ROUTING_STARTED_AT_SETTING = "conversation_routing_started_at"
# The master's system settings recording each computer's export at the changeover.
CHANGEOVER_EXPORT_SETTING_PREFIX = "conversation_changeover_exported:"
# The shared key the master publishes the activation under; it never expires.
CUTOVER_PUBLICATION_KEY = "teleclaude:conversation_routing:activated_at"
# How long a message reaching the master during the changeover waits for routing to start.
CHANGEOVER_WAIT_S = 180.0
# How often a waiting message checks whether the changeover can complete.
CHANGEOVER_POLL_S = 2.0
# How often every computer runs its conversation upkeep.
CONVERSATION_UPKEEP_INTERVAL_S = 30.0
# The adapters whose messages reach every computer.
SHARED_ORIGINS = frozenset({InputOrigin.DISCORD.value, InputOrigin.WHATSAPP.value})

_ADOPTION_COMPLETE_EVENT = "conversation_bindings_adopted"
_ARMED_EVENT = "conversation_routing_armed"
_CHANGEOVER_HELD_EVENT = "conversation_changeover_held"
_CHANGEOVER_EXPORTED_EVENT = "conversation_changeover_exported"
_ROUTING_STARTED_EVENT = "conversation_routing_started"
_CHANGEOVER_TIMED_OUT_EVENT = "conversation_changeover_timed_out"
_UPKEEP_FAILED_EVENT = "conversation_upkeep_failed"
_ACTIVATION_UNKNOWN_EVENT = "conversation_activation_unreadable"


class CutoverUnreadable(Exception):
    """The shared store holding the published activation could not be read."""


class LegacyHandlingGate:
    """Counts the messages this computer admitted to its own, pre-cutover handling and has not finished.

    A message is admitted before its computer's cutover state is read and
    released when its handling ends, so once the computer has armed, the gate
    being idle means nothing it admitted on its own is still running.
    """

    def __init__(self) -> None:
        self._in_flight = 0

    @asynccontextmanager
    async def admit(self) -> AsyncIterator[None]:
        """Hold one message's admission for as long as it is handled."""
        self._in_flight += 1
        try:
            yield
        finally:
            self._in_flight -= 1

    def idle(self) -> bool:
        """Whether no admitted message is still being handled."""
        return self._in_flight == 0


# This computer's one gate: the seam admits through it and the heartbeat reads it.
LEGACY_HANDLING = LegacyHandlingGate()


class SharedRoutingState(StrEnum):
    """This computer's side of the cutover."""

    # Not armed: the adapter handles the conversation as before the cutover.
    BEFORE_CUTOVER = "before_cutover"
    # Not armed, and whether the master activated cannot be told: nothing is handled on its own.
    UNKNOWN = "unknown"
    # The master has armed and waits for every receiving computer before it routes.
    CHANGING_OVER = "changing_over"
    # Armed; the master routes, every other computer leaves it to the master.
    ACTIVE = "active"


class _Publication(StrEnum):
    PUBLISHED = "published"
    ABSENT = "absent"
    UNREADABLE = "unreadable"


class _HeldReason(StrEnum):
    LOCAL_HANDLING_IN_FLIGHT = "local_handling_in_flight"
    LACKING_FEATURE = "computers_lack_conversation_entry"
    NOT_ARMED = "computers_not_armed"
    EXPORT_UNANSWERED = "export_unanswered"


async def shared_routing_activated(db: Db) -> bool:
    """Whether this computer has armed."""
    return await db.get_system_setting(ROUTING_ACTIVATED_AT_SETTING) is not None


def receives_shared_conversations(member: FleetMember) -> bool:
    """Whether a computer receives shared-adapter messages; one that does not announce its adapters may."""
    adapters = member.conversation_adapters
    return adapters is None or bool(adapters & SHARED_ORIGINS)


async def routing_announced(db: Db) -> bool:
    """What this computer announces: armed, and nothing it admitted on its own still running."""
    return await shared_routing_activated(db) and LEGACY_HANDLING.idle()


async def _activation_publication(env: ConversationEnvironment, fleet: FleetView) -> _Publication:
    if any(member.routing_active for member in fleet.peers):
        return _Publication.PUBLISHED
    try:
        published = await env.read_cutover()
    except CutoverUnreadable:
        return _Publication.UNREADABLE
    return _Publication.PUBLISHED if published is not None else _Publication.ABSENT


async def shared_routing_state(env: ConversationEnvironment, fleet: FleetView) -> SharedRoutingState:
    """This computer's side of the cutover, arming it when the activation has been published."""
    if not await shared_routing_activated(env.db):
        publication = await _activation_publication(env, fleet)
        if publication is _Publication.UNREADABLE:
            logger.warning(_ACTIVATION_UNKNOWN_EVENT, computer=env.host)
            return SharedRoutingState.UNKNOWN
        if publication is _Publication.ABSENT:
            return SharedRoutingState.BEFORE_CUTOVER
        await env.db.set_system_setting(ROUTING_ACTIVATED_AT_SETTING, env.now_iso())
        logger.info(_ARMED_EVENT, computer=env.host)
    if fleet.local.is_master and await env.db.get_system_setting(ROUTING_STARTED_AT_SETTING) is None:
        return SharedRoutingState.CHANGING_OVER
    return SharedRoutingState.ACTIVE


async def activate_routing(env: ConversationEnvironment) -> None:
    """On the master, once every expected source has answered: arm and publish the activation.

    Publishing repeats on every pass, so a lost write or a reset store is restored.
    """
    if not await shared_routing_activated(env.db):
        await env.db.set_system_setting(ROUTING_ACTIVATED_AT_SETTING, env.now_iso())
        logger.info(_ADOPTION_COMPLETE_EVENT)
    activated_at = await env.db.get_system_setting(ROUTING_ACTIVATED_AT_SETTING)
    if activated_at is not None:
        await env.publish_cutover(activated_at)


def _changeover_export_setting(computer: str) -> str:
    return CHANGEOVER_EXPORT_SETTING_PREFIX + computer


async def _export_at_changeover(env: ConversationEnvironment, computer: str) -> bool:
    """Bind ``computer``'s open sessions once it no longer creates any on its own; whether it answered."""
    if await env.db.get_system_setting(_changeover_export_setting(computer)) is not None:
        return True
    exported = await env.export_from(computer, None)
    if exported is None:
        return False
    await seed_bindings(env.db, computer, exported)
    await env.db.set_system_setting(_changeover_export_setting(computer), env.now_iso())
    logger.info(_CHANGEOVER_EXPORTED_EVENT, computer=computer, sessions=len(exported))
    return True


async def try_start_routing(env: ConversationEnvironment) -> bool:
    """On the armed master: start routing when every receiving computer has armed; whether it routes."""
    async with env.changeover_lock:
        if await env.db.get_system_setting(ROUTING_STARTED_AT_SETTING) is not None:
            return True
        fleet = await env.observe_fleet()
        if not fleet.local.is_master or not await shared_routing_activated(env.db):
            return False
        if not env.legacy.idle():
            logger.info(_CHANGEOVER_HELD_EVENT, reason=_HeldReason.LOCAL_HANDLING_IN_FLIGHT.value, computers=[env.host])
            return False
        lacking = fleet.lacking_conversation_entry()
        if lacking:
            logger.info(_CHANGEOVER_HELD_EVENT, reason=_HeldReason.LACKING_FEATURE.value, computers=lacking)
            return False
        receivers = [member for member in fleet.peers if receives_shared_conversations(member)]
        not_armed = [member.name for member in receivers if not member.routing_active]
        if not_armed:
            logger.info(_CHANGEOVER_HELD_EVENT, reason=_HeldReason.NOT_ARMED.value, computers=not_armed)
            return False
        for computer in (env.host, *(member.name for member in receivers)):
            if not await _export_at_changeover(env, computer):
                logger.info(_CHANGEOVER_HELD_EVENT, reason=_HeldReason.EXPORT_UNANSWERED.value, computers=[computer])
                return False
        await env.db.set_system_setting(ROUTING_STARTED_AT_SETTING, env.now_iso())
        logger.info(_ROUTING_STARTED_EVENT)
        return True


async def changeover_exports_outstanding(env: ConversationEnvironment) -> list[str]:
    """The computers named in the adoption run that have not been exported at the changeover."""
    sources = await env.db.list_conversation_adoption_sources()
    return [
        source.computer
        for source in sources
        if await env.db.get_system_setting(_changeover_export_setting(source.computer)) is None
    ]


async def await_routing_start(env: ConversationEnvironment) -> bool:
    """Hold a message reaching the master during the changeover until routing starts; whether it did."""
    for _ in range(int(CHANGEOVER_WAIT_S / CHANGEOVER_POLL_S)):
        if await try_start_routing(env):
            return True
        await env.sleep(CHANGEOVER_POLL_S)
    logger.warning(_CHANGEOVER_TIMED_OUT_EVENT, waited_s=CHANGEOVER_WAIT_S)
    return False


async def export_returning_computers(env: ConversationEnvironment) -> None:
    """After the start: bind the sessions of a computer that was away at the changeover, once it has armed."""
    fleet = await env.observe_fleet()
    for member in fleet.peers:
        if receives_shared_conversations(member) and member.routing_active:
            await _export_at_changeover(env, member.name)


async def run_conversation_upkeep(env: ConversationEnvironment, shutdown_event: asyncio.Event) -> None:
    """Every interval: every computer arms once the activation is published; the master also runs
    the adoption run, publishes the activation, completes the changeover, exports computers that
    come back, and closes orphans.
    """
    while not shutdown_event.is_set():
        try:
            await shared_routing_state(env, await env.observe_fleet())
            if config.computer.is_master:
                if await run_adoption_pass(env):
                    await activate_routing(env)
                if await try_start_routing(env):
                    await export_returning_computers(env)
                await run_orphan_pass(env)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error(_UPKEEP_FAILED_EVENT, error=str(exc), exc_info=True)
        try:
            await asyncio.wait_for(shutdown_event.wait(), timeout=CONVERSATION_UPKEEP_INTERVAL_S)
        except TimeoutError:
            continue


__all__ = [
    "CHANGEOVER_EXPORT_SETTING_PREFIX",
    "CHANGEOVER_POLL_S",
    "CHANGEOVER_WAIT_S",
    "CONVERSATION_UPKEEP_INTERVAL_S",
    "CUTOVER_PUBLICATION_KEY",
    "LEGACY_HANDLING",
    "ROUTING_ACTIVATED_AT_SETTING",
    "ROUTING_STARTED_AT_SETTING",
    "SHARED_ORIGINS",
    "CutoverUnreadable",
    "LegacyHandlingGate",
    "SharedRoutingState",
    "activate_routing",
    "await_routing_start",
    "changeover_exports_outstanding",
    "export_returning_computers",
    "receives_shared_conversations",
    "routing_announced",
    "run_conversation_upkeep",
    "shared_routing_activated",
    "shared_routing_state",
    "try_start_routing",
]
