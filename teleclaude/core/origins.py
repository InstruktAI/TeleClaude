"""Input origin constants for session tracking."""

from enum import Enum


class InputOrigin(str, Enum):
    """Input origin for session tracking."""

    TELEGRAM = "telegram"
    DISCORD = "discord"
    WHATSAPP = "whatsapp"
    WEB = "web"
    REDIS = "redis"
    API = "api"
    TERMINAL = "terminal"
    HOOK = "hook"
