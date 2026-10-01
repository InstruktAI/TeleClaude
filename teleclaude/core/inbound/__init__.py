"""Inbound seams: origin-addressed resolve-or-create, and the conversation turn contract.

The conversation seam itself is ``teleclaude.core.inbound.conversation``; adapters
import it directly so this package stays a light import for every adapter.
"""

from .models import (
    BindOutcome,
    ConversationRef,
    ConversationTurn,
    EntryGesture,
    InboundBinding,
    InboundSessionPolicy,
    TurnCreation,
    TurnModality,
)
from .resolver import handle_inbound_message, resolve_binding_key, resolve_or_create_bound_session

__all__ = [
    "BindOutcome",
    "ConversationRef",
    "ConversationTurn",
    "EntryGesture",
    "InboundBinding",
    "InboundSessionPolicy",
    "TurnCreation",
    "TurnModality",
    "handle_inbound_message",
    "resolve_binding_key",
    "resolve_or_create_bound_session",
]
