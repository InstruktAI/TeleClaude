"""Input origin constants for session tracking."""

from enum import Enum


class InputOrigin(str, Enum):
    """Input origin for session tracking."""

    TELEGRAM = "telegram"
    DISCORD = "discord"
    WHATSAPP = "whatsapp"
    GITHUB = "github"
    TERMINAL = "terminal"
    REMINDER = "reminder"
