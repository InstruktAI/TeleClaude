"""Value objects for the inbound seams: origin-addressed resolve-or-create, and conversation turns.

Mirrors ``core/delivery/models.py`` on the inbound side — see
docs/local/design/architecture/ui-adapter.md for the resolve-or-create
seam invariants these types implement, and the conversation-entry spec
(`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`) for the
conversation turn contract.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from hashlib import sha256
from typing import TYPE_CHECKING

from teleclaude.core.command_input import CommandInputMode
from teleclaude.core.models import ENDPOINT_SECTION, EndpointStampField, Session, SessionEntryPoint
from teleclaude.core.origins import InputOrigin

if TYPE_CHECKING:
    from teleclaude.core.endpoints import EntryIdentifier
    from teleclaude.core.identity import IdentityContext

# The origin-section fields that key a Discord direct-message and a WhatsApp conversation.
DISCORD_DM_KEY_FIELD = "channel_id"
WHATSAPP_KEY_FIELD = "phone_number"
_CONVERSATION_KEY_TEMPLATE = "{origin}:{key_field}:{key}"
_HASHED_KEY_LENGTH = 16


@dataclass(frozen=True)
class InboundBinding:
    """A resolved inbound identity: the platform origin plus its binding key.

    Mirrors ``Destination`` on the outbound side — the concrete identity
    coords an adapter's resolve-or-create policy is scoped to, without
    carrying a ``Session``.
    """

    origin: str
    origin_metadata: dict[str, object]  # guard: loose-dict - adapter-parsed inbound payload
    binding_key: str | None = None


async def _no_dispatch(_session: Session) -> None:
    """Default for callers that only need `resolve_or_create_bound_session`'s explicit is_new.

    Some adapter paths (e.g. Discord guild messages) gate delivery behind extra,
    path-specific checks (authorization, relay-diversion) that must run between
    resolve-or-create and delivery, so they call the resolver directly instead of
    `handle_inbound_message` and never invoke `dispatch`.
    """


@dataclass(frozen=True)
class InboundSessionPolicy:
    """Adapter-supplied resolve-or-create callbacks feeding the shared seam.

    Parameterizes the one divergent piece across platforms — project/workspace
    resolution and launch-intent construction differ per adapter — as
    callbacks rather than a per-adapter fork of the orchestration.
    """

    find: Callable[[], Awaitable[Session | None]]
    create: Callable[[], Awaitable[Session | None]]
    reconcile: Callable[[Session], Awaitable[Session]]
    dispatch: Callable[[Session], Awaitable[None]] = _no_dispatch


@dataclass(frozen=True)
class ConversationRef:
    """One adapter's private channel with one person, and the key its sessions carry.

    ``key_field`` names the field of the origin section the conversation's
    sessions carry ``key`` in. ``reaches_every_computer`` marks adapters whose
    inbound messages every computer receives, where the mesh master alone
    decides. ``carries_desk_entry`` marks adapters whose conversations can enter
    a help desk; on the others a desk identifier is a miss and no desk session
    is the conversation's session. ``refine`` lets an adapter exclude its own
    non-conversation sessions from the per-computer lookup.
    """

    origin: InputOrigin
    key_field: str
    key: str
    reaches_every_computer: bool
    carries_desk_entry: bool
    refine: Callable[[Session], bool] | None = None

    @property
    def hashed_key(self) -> str:
        """A stable, non-reversible conversation key for logs and in-memory gates."""
        raw = _CONVERSATION_KEY_TEMPLATE.format(origin=self.origin.value, key_field=self.key_field, key=self.key)
        return sha256(raw.encode()).hexdigest()[:_HASHED_KEY_LENGTH]

    def admits(self, session: Session) -> bool:
        """Whether ``session`` belongs to this conversation after the adapter's own refinement."""
        return self.refine is None or self.refine(session)


def is_superseded(session: Session) -> bool:
    """Whether a later entry of the session's conversation took the conversation elsewhere."""
    return session.get_origin_section(ENDPOINT_SECTION).get(EndpointStampField.SUPERSEDED_AT) is not None


class EntryGesture(StrEnum):
    """What a turn carries toward an endpoint."""

    # An ordinary message: no identifier.
    NONE = "none"
    # Exactly an entry identifier (``identifier`` is set).
    IDENTIFIER = "identifier"
    # An entry attempt whose parameter is no identifier: a miss.
    UNRESOLVABLE = "unresolvable"
    # The adapter's entry link without a parameter.
    BARE = "bare"


class TurnModality(StrEnum):
    """Whether a turn's content can ride along into a new session's launch."""

    TEXT = "text"
    MEDIA = "media"


class BindOutcome(StrEnum):
    """Result of binding a platform account through an invitation token."""

    ACCEPTED = "accepted"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class TurnCreation:
    """What a session created for this conversation carries: entry point, input mode, flat origin metadata."""

    entry_point: SessionEntryPoint
    origin_metadata: Mapping[str, object] = field(default_factory=dict)
    command_input_mode: CommandInputMode = CommandInputMode.ORDINARY


@dataclass(frozen=True)
class ConversationTurn:
    """One inbound message of a conversation, as an adapter hands it to the core.

    The adapter carries the identifier and supplies its own delivery, reply
    and invitation binding; it decides nothing. ``deliver`` runs the adapter's
    dispatch of this message into a session on this computer.

    ``designated_person`` is the registered person a channel the adapter
    provisioned serves, for adapters whose conversation is a shared channel
    rather than one person's private chat. A designated turn carries no entry
    identifier, and the core admits it only from that person.
    """

    conversation: ConversationRef
    sender: IdentityContext
    text: str
    gesture: EntryGesture
    creation: TurnCreation
    deliver: Callable[[Session], Awaitable[None]]
    reply: Callable[[str], Awaitable[None]]
    bind_invite: Callable[[str], Awaitable[BindOutcome]]
    identifier: EntryIdentifier | None = None
    modality: TurnModality = TurnModality.TEXT
    designated_person: str | None = None


__all__ = [
    "DISCORD_DM_KEY_FIELD",
    "WHATSAPP_KEY_FIELD",
    "BindOutcome",
    "ConversationRef",
    "ConversationTurn",
    "EntryGesture",
    "InboundBinding",
    "InboundSessionPolicy",
    "TurnCreation",
    "TurnModality",
    "is_superseded",
]
