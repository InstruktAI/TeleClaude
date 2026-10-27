"""Default daemon configuration blueprint, merged under the user config.

``DEFAULT_CONFIG`` is the defaults/constants blob, not the public contract. What is
public and human-editable is declared by the per-field ``tier`` markers on
``TeleclaudeConfig`` (``local/projects/teleclaude/policy/config-public-surface``); the generated
``templates/config.yml`` sample follows from those markers, not from this blob.
"""

from __future__ import annotations

from teleclaude.constants import (
    REDIS_MAX_CONNECTIONS,
    REDIS_MESSAGE_STREAM_MAXLEN,
    REDIS_OUTPUT_STREAM_MAXLEN,
    REDIS_OUTPUT_STREAM_TTL,
    REDIS_SOCKET_TIMEOUT,
)

DEFAULT_CONFIG: dict[str, object] = {  # guard: loose-dict - YAML configuration structure
    "hook_outbox": {
        "poll_interval_s": 1,
        "batch_size": 25,
        "lock_ttl_s": 30,
        "base_backoff_s": 1,
        "max_backoff_s": 60,
        "session_idle_timeout_s": 5,
        "session_max_pending": 32,
        "session_critical_reserve": 8,
        "summary_interval_s": 15,
        "backlog_warn_threshold": 20,
        "lag_warn_threshold_s": 3,
        "warn_log_interval_s": 15,
        "max_lag_samples": 2048,
        "staleness_ttl_s": 300,
    },
    "api": {
        "tcp_port": 8420,
        "watch_interval_s": 5,
        "watch_lag_threshold_ms": 250,
        "watch_inflight_threshold_s": 1,
        "watch_dump_cooldown_s": 30,
        "mcp_reaper_interval_s": 30,
        "ws_control_send_timeout_s": 30,
        "ws_default_send_timeout_s": 15,
        "ws_replaceable_send_timeout_s": 5,
    },
    "daemon": {
        "api_restart_max": 5,
        "api_restart_window_s": 60,
        "api_restart_backoff_s": 1,
        "resource_snapshot_interval_s": 60,
        "launchd_watch_interval_s": 300,
        "launchd_watch_enabled": True,
        "startup_gate_timeout_s": 15,
        "startup_gate_poll_interval_s": 0.25,
        "agent_prompt_ready_timeout_s": 60,
        "log_level": "INFO",
        "legacy_gemini_root": "~/.gemini/tmp",
    },
    "computer": {
        # No name default: a computer without a configured name fails its load instead of joining as "unknown".
        # Empty/None sentinels mark fields the loader derives at runtime.
        "user": "",
        "role": "general",
        "timezone": "Europe/Amsterdam",
        "default_working_dir": "",
        "is_master": False,
        "is_ingress_node": False,
        "host": None,
    },
    "remote_computers": {},
    "redis": {
        "local": {
            "url": None,
            "username": None,
            "password": None,
            "max_connections": REDIS_MAX_CONNECTIONS,
            "socket_timeout": REDIS_SOCKET_TIMEOUT,
        },
        "cluster": {
            "url": None,
            "username": None,
            "password": None,
            "max_connections": REDIS_MAX_CONNECTIONS,
            "socket_timeout": REDIS_SOCKET_TIMEOUT,
            "message_stream_maxlen": REDIS_MESSAGE_STREAM_MAXLEN,
            "output_stream_maxlen": REDIS_OUTPUT_STREAM_MAXLEN,
            "output_stream_ttl": REDIS_OUTPUT_STREAM_TTL,
        },
    },
    "telegram": {
        "enabled": False,
        "bot_token": None,
    },
    "discord": {
        "enabled": False,
        "token": None,
        "guild_id": None,
    },
    "whatsapp": {
        "enabled": False,
        "phone_number_id": None,
        "access_token": None,
        "webhook_secret": None,
        "verify_token": None,
        "business_number": None,
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
                "api_key": None,
            },
            "elevenlabs": {
                "enabled": False,
                "voices": [],
                "api_key": None,
            },
            "mlx": {
                "enabled": False,
                "cli_bin": None,
                "instruct": "A clear, natural conversational voice.",
            },
        },
    },
    "stt": {
        "enabled": False,
        "services": {
            "openai": {
                "enabled": False,
                "api_key": None,
            },
            "parakeet": {
                "enabled": False,
                "model": "mlx-community/parakeet-tdt-0.6b-v3",
                "cli_bin": None,
            },
        },
    },
    "chiptunes": {
        "enabled": False,
        "music_dir": None,
        "volume": 1.0,
    },
    "email": {
        "enabled": False,
        "smtp_username": None,
        "smtp_key": None,
        "email_from": None,
        "reply_to": None,
        "smtp_relay": "smtp-relay.brevo.com:587",
    },
    "backup": {
        "aws_access_key_id": None,
        "aws_secret_access_key": None,
        "aws_s3_host": None,
        "aws_s3_region": None,
        "aws_s3_bucket": None,
        "backup_prefix": None,
    },
    "database_url": None,
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
    "deployment": {
        "channel": "stable",
    },
    "experiments": [],
}
