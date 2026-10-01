"""The shared Discord child claim vocabulary the command boundary accepts."""

from enum import Enum


class DiscordThreadClaimAction(str, Enum):
    """Typed mutations accepted by the shared Discord child claim ledger."""

    OBSERVE = "observe"
    CLAIM = "claim"
    COMPLETE_INVENTORY = "complete_inventory"
    OPEN_EPOCH = "open_epoch"


class DiscordThreadClaimKind(str, Enum):
    """Shared Discord child kinds accepted by the command boundary."""

    HELP_DESK_SESSION = "help_desk_session"
    ESCALATION_RELAY = "escalation_relay"


class DiscordThreadClaimLifecycle(str, Enum):
    """Lifecycle values accepted by the command boundary."""

    PENDING = "pending"
    ACTIVE = "active"
    TERMINAL = "terminal"
