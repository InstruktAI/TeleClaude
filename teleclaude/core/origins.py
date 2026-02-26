"""Input origin constants for session tracking."""

from enum import Enum


class InputOrigin(str, Enum):
    TELEGRAM = "telegram"
    DISCORD = "discord"
    WHATSAPP = "whatsapp"
    REDIS = "redis"
    API = "api"
    TERMINAL = "terminal"
