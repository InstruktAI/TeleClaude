"""Input origin constants for session tracking."""

from enum import Enum


class InputOrigin(str, Enum):
    TELEGRAM = "telegram"
    DISCORD = "discord"
    REDIS = "redis"
    API = "api"
    TERMINAL = "terminal"
    HOOK = "hook"
