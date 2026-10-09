"""The live fleet as conversation routing sees it: who hosts which desk, who decides, who runs what.

Built from this computer's own facts plus every live peer's heartbeat. The
release boundary for endpoint routing is the fleet capability map's
``conversation-entry`` feature: until every live computer carries it, desk
entries are misses and the links command refuses.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from instrukt_ai_logging import get_logger
from redis.exceptions import RedisError

from teleclaude.config.machine import config
from teleclaude.core.endpoints import hosted_help_desks
from teleclaude.core.models import PeerInfo
from teleclaude.core.origins import InputOrigin
from teleclaude.core.reconciliation import (
    CONVERSATION_ENTRY_FEATURE_ID,
    DEFAULT_FEATURE_ID_REGISTRY,
    FleetCapabilityEntry,
    FleetCapabilityMap,
    decode_capability_set,
)
from teleclaude.core.redis_utils import scan_keys
from teleclaude.transport.peer_heartbeat import (
    CONVERSATION_ADAPTERS_FIELD,
    CONVERSATION_ROUTING_FIELD,
    HELP_DESKS_FIELD,
    decode_announced_strings,
    decode_heartbeat_payload,
    decode_optional_announced_strings,
    heartbeat_scan_pattern,
)
from teleclaude.transport.redis_client import create_redis_client

if TYPE_CHECKING:
    from teleclaude.core.adapter_client import AdapterClient

logger = get_logger(__name__)

_PEER_NAME_FIELD = "name"
_HEARTBEAT_NAME_FIELD = "computer_name"
_PEER_CAPABILITY_SET_FIELD = "capability_set"
_PEER_IS_MASTER_FIELD = "is_master"
_PEER_VERSION_FIELD = "version"
_PEER_CHANNEL_FIELD = "channel"
_MASTER_CONFLICT_EVENT = "conversation_master_conflict"
_FLEET_OBSERVATION_FAILED_EVENT = "fleet_observation_failed"


@dataclass(frozen=True)
class FleetMember:
    """One live computer: its capabilities, the desks it announces and the adapters it runs."""

    name: str
    is_master: bool
    capability_set: frozenset[str]
    help_desks: tuple[str, ...] = ()
    # ``None`` when the computer does not announce its adapters (an older build).
    conversation_adapters: frozenset[str] | None = None
    version: str | None = None
    channel: str | None = None
    # Whether the computer announces that shared-adapter routing is active on it.
    routing_active: bool = False

    def runs(self, origin: InputOrigin) -> bool:
        """Whether this computer runs ``origin``; an unannounced set counts as running it."""
        return self.conversation_adapters is None or origin.value in self.conversation_adapters


@dataclass(frozen=True)
class FleetView:
    """This computer plus every live peer, as one observation."""

    local: FleetMember
    peers: tuple[FleetMember, ...]

    @property
    def members(self) -> tuple[FleetMember, ...]:
        """Every live computer, this one included, in name order."""
        return tuple(sorted((self.local, *self.peers), key=lambda member: member.name))

    def capability_map(self) -> FleetCapabilityMap:
        """The fleet capability map over these live computers."""
        observed_at = datetime.now(UTC)
        return FleetCapabilityMap(
            tuple(
                FleetCapabilityEntry(
                    computer=member.name,
                    version=member.version,
                    channel=member.channel,
                    capability_set=member.capability_set,
                    last_advertised_at=observed_at,
                )
                for member in self.members
            )
        )

    def conversation_entry_safe(self) -> bool:
        """Whether every live computer carries endpoint routing."""
        return self.capability_map().safe_to_require(CONVERSATION_ENTRY_FEATURE_ID)

    def lacking_conversation_entry(self) -> list[str]:
        """The live computers that do not carry endpoint routing yet."""
        return [member.name for member in self.members if CONVERSATION_ENTRY_FEATURE_ID not in member.capability_set]

    def desk_announcements(self) -> dict[str, tuple[str, ...]]:
        """Each live computer's announced desk identifiers."""
        return {member.name: member.help_desks for member in self.members}

    def master(self) -> FleetMember | None:
        """The single live mesh master; none, or a conflict between several, is no master."""
        masters = [member for member in self.members if member.is_master]
        if len(masters) > 1:
            logger.error(_MASTER_CONFLICT_EVENT, computers=[member.name for member in masters])
            return None
        return masters[0] if masters else None

    def routing_master(self, origin: InputOrigin) -> FleetMember | None:
        """The master, when it is live and runs ``origin``; the only computer that routes there."""
        master = self.master()
        return master if master is not None and master.runs(origin) else None

    def unavailable_replier(self, origin: InputOrigin) -> str | None:
        """The lowest-named live computer running ``origin``: the one that answers while nobody routes."""
        running = [member.name for member in self.members if member.runs(origin)]
        return running[0] if running else None


def local_conversation_adapters() -> frozenset[str]:
    """The conversation adapters this computer runs."""
    enabled = {
        InputOrigin.TELEGRAM: config.telegram.enabled,
        InputOrigin.DISCORD: config.discord.enabled,
        InputOrigin.WHATSAPP: config.whatsapp.enabled,
    }
    return frozenset(origin.value for origin, is_enabled in enabled.items() if is_enabled)


def local_fleet_member(help_desks: Sequence[str]) -> FleetMember:
    """This computer, announcing ``help_desks``."""
    return FleetMember(
        name=config.computer.name,
        is_master=bool(config.computer.is_master),
        capability_set=DEFAULT_FEATURE_ID_REGISTRY.carried_set(),
        help_desks=tuple(help_desks),
        conversation_adapters=local_conversation_adapters(),
        channel=config.deployment.channel,
    )


def fleet_member_from_peer(peer: Mapping[str, object]) -> FleetMember:
    """One live peer from its discovered heartbeat fields."""
    adapters = decode_optional_announced_strings(peer.get(CONVERSATION_ADAPTERS_FIELD))
    version = peer.get(_PEER_VERSION_FIELD)
    channel = peer.get(_PEER_CHANNEL_FIELD)
    return FleetMember(
        name=cast(str, peer.get(_PEER_NAME_FIELD)),
        is_master=peer.get(_PEER_IS_MASTER_FIELD) is True,
        capability_set=frozenset(decode_capability_set(peer.get(_PEER_CAPABILITY_SET_FIELD))),
        help_desks=tuple(decode_announced_strings(peer.get(HELP_DESKS_FIELD))),
        conversation_adapters=frozenset(adapters) if adapters is not None else None,
        version=version if isinstance(version, str) else None,
        channel=channel if isinstance(channel, str) else None,
        routing_active=peer.get(CONVERSATION_ROUTING_FIELD) is True,
    )


def build_fleet_view(local: FleetMember, peers: Sequence[Mapping[str, object]]) -> FleetView:
    """Combine this computer and its discovered peers into one view."""
    members = tuple(fleet_member_from_peer(peer) for peer in peers if isinstance(peer.get(_PEER_NAME_FIELD), str))
    return FleetView(local=local, peers=tuple(member for member in members if member.name != local.name))


def fleet_member_from_peer_info(peer: PeerInfo) -> FleetMember:
    """One live peer from the transport's own peer record."""
    adapters = peer.conversation_adapters
    return FleetMember(
        name=peer.name,
        is_master=peer.is_master is True,
        capability_set=frozenset(peer.capability_set),
        help_desks=tuple(peer.help_desks),
        conversation_adapters=frozenset(adapters) if adapters is not None else None,
        version=peer.version,
        channel=peer.channel,
        routing_active=peer.conversation_routing,
    )


async def observe_fleet_from_heartbeats() -> FleetView:
    """Observe the fleet straight from the heartbeat keys, for a process that holds no transport."""
    redis_config = config.redis
    redis_client = create_redis_client(
        redis_config.url,
        password=redis_config.password,
        max_connections=redis_config.max_connections,
        socket_timeout=redis_config.socket_timeout,
    )
    peers: list[Mapping[str, object]] = []
    try:
        for key in await scan_keys(redis_client, heartbeat_scan_pattern()):
            payload = await redis_client.get(key)
            heartbeat = decode_heartbeat_payload(payload) if payload else None
            if heartbeat is not None:
                peers.append({**heartbeat, _PEER_NAME_FIELD: heartbeat.get(_HEARTBEAT_NAME_FIELD)})
    finally:
        await redis_client.aclose()
    desks = await asyncio.to_thread(hosted_help_desks)
    return build_fleet_view(local_fleet_member([desk.render() for desk in desks]), peers)


async def contraction_answer_from_heartbeats(feature_id: str) -> bool:
    """Whether every live computer carries the feature-ID, observed now; an observation that fails is not yet safe."""
    try:
        view = await observe_fleet_from_heartbeats()
    except (RedisError, OSError):
        logger.warning(_FLEET_OBSERVATION_FAILED_EVENT, feature_id=feature_id, exc_info=True)
        return False
    return view.capability_map().safe_to_contract(feature_id)


async def observe_fleet(client: AdapterClient) -> FleetView:
    """Observe this computer's hosted desks and every live peer's heartbeat."""
    desks = await asyncio.to_thread(hosted_help_desks)
    local = local_fleet_member([desk.render() for desk in desks])
    return build_fleet_view(local, await client.discover_peers())


__all__ = [
    "FleetMember",
    "FleetView",
    "build_fleet_view",
    "contraction_answer_from_heartbeats",
    "fleet_member_from_peer",
    "fleet_member_from_peer_info",
    "local_conversation_adapters",
    "local_fleet_member",
    "observe_fleet",
    "observe_fleet_from_heartbeats",
]
