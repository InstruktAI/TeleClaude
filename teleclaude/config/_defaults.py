"""Default daemon configuration blueprint, merged under the user config."""

from __future__ import annotations

from teleclaude.constants import (
    REDIS_MAX_CONNECTIONS,
    REDIS_MESSAGE_STREAM_MAXLEN,
    REDIS_OUTPUT_STREAM_MAXLEN,
    REDIS_OUTPUT_STREAM_TTL,
    REDIS_SOCKET_TIMEOUT,
)

DEFAULT_CONFIG: dict[str, object] = {  # guard: loose-dict - YAML configuration structure
    "computer": {
        "name": "unknown",
        # Empty/None sentinels mark fields the loader derives at runtime.
        "user": "",
        "role": "general",
        "timezone": "Europe/Amsterdam",
        "default_working_dir": "",
        "is_master": False,
        "is_ingress_node": False,
        "trusted_dirs": [],
        "host": None,
    },
    "remote_computers": {},
    "redis": {
        "url": "redis://localhost:6379",
        "password": None,
        "max_connections": REDIS_MAX_CONNECTIONS,
        "socket_timeout": REDIS_SOCKET_TIMEOUT,
        "message_stream_maxlen": REDIS_MESSAGE_STREAM_MAXLEN,
        "output_stream_maxlen": REDIS_OUTPUT_STREAM_MAXLEN,
        "output_stream_ttl": REDIS_OUTPUT_STREAM_TTL,
    },
    "telegram": {
        "enabled": False,
    },
    "discord": {
        "enabled": False,
        "token": None,
        "guild_id": None,
        "help_desk_channel_id": None,
        "escalation_channel_id": None,
        "all_sessions_channel_id": None,
        "operator_chat_channel_id": None,
        "announcements_channel_id": None,
        "general_channel_id": None,
        "categories": None,
    },
    "whatsapp": {
        "enabled": False,
        "phone_number_id": None,
        "access_token": None,
        "webhook_secret": None,
        "verify_token": None,
        "template_name": None,
        "template_language": "en_US",
    },
    "tts": {
        "enabled": False,
        "events": {
            "session_start": {
                "enabled": False,
            },
        },
        "services": {
            "pyttsx3": {
                "enabled": True,
                "voices": [],
            },
            "macos": {
                "enabled": False,
                "voices": [],
            },
            "openai": {
                "enabled": False,
                "voices": [],
            },
            "elevenlabs": {
                "enabled": False,
                "voices": [],
            },
        },
    },
    "chiptunes": {
        "enabled": False,
        "music_dir": None,
        "volume": 1.0,
    },
    "workflow": {
        "autostart": {
            "feature": False,
            "change": False,
            "bug": False,
            "task": False,
        },
        "runner": "autostart",
        "max_todo_dispatch": 5,
    },
    "experiments": [],
}
