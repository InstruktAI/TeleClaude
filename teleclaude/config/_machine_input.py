"""Declared raw shapes for the machine configuration parsers."""

from __future__ import annotations

from teleclaude.config._chiptunes import CHIPTUNES_INPUT
from teleclaude.config._remote_computers import REMOTE_COMPUTERS_INPUT
from teleclaude.config._runtime_tunables import API_INPUT, DAEMON_INPUT, HOOK_OUTBOX_INPUT
from teleclaude.config._strictness import OPEN, SCALAR, ClosedMapping, InputList, NamedMapping
from teleclaude.config._summarizer import SUMMARIZER_INPUT

_MODE_QOS_INPUT = ClosedMapping({"mode": SCALAR})
_TELEGRAM_QOS_INPUT = ClosedMapping(
    {
        "enabled": SCALAR,
        "group_mpm": SCALAR,
        "output_budget_ratio": SCALAR,
        "reserve_mpm": SCALAR,
        "min_session_tick_s": SCALAR,
        "active_emitter_window_s": SCALAR,
        "active_emitter_ema_alpha": SCALAR,
        "rounding_ms": SCALAR,
    }
)
_TRUSTED_DIRECTORY_INPUT = ClosedMapping({"name": SCALAR, "desc": SCALAR, "path": SCALAR})
_TTS_VOICE_INPUT = ClosedMapping({"name": SCALAR, "voice_id": SCALAR, "params": OPEN})
_TTS_SERVICE_INPUT = ClosedMapping(
    {
        "enabled": SCALAR,
        "voices": InputList(_TTS_VOICE_INPUT),
        "model": SCALAR,
        "api_key": SCALAR,
        "params": OPEN,
        "cli_bin": SCALAR,
        "instruct": SCALAR,
        "discord_voice": SCALAR,
    }
)
_TTS_INPUT = ClosedMapping(
    {
        "enabled": SCALAR,
        "service_priority": InputList(SCALAR),
        "events": NamedMapping(ClosedMapping({"enabled": SCALAR, "messages": InputList(SCALAR), "message": SCALAR})),
        "services": NamedMapping(_TTS_SERVICE_INPUT),
    }
)
_STT_INPUT = ClosedMapping(
    {
        "enabled": SCALAR,
        "service_priority": InputList(SCALAR),
        "services": NamedMapping(
            ClosedMapping({"enabled": SCALAR, "model": SCALAR, "api_key": SCALAR, "cli_bin": SCALAR})
        ),
    }
)
_PROCESS_JANITOR_INPUT = ClosedMapping(
    {
        "scan_interval_seconds": SCALAR,
        "default_signature_ttl_seconds": SCALAR,
        "lease_ttl_seconds": SCALAR,
        "dry_run_default": SCALAR,
        "reap_revalidation_seconds": SCALAR,
    }
)
_WORKFLOW_INPUT = ClosedMapping(
    {
        "autostart": ClosedMapping({"feature": SCALAR, "change": SCALAR, "bug": SCALAR, "task": SCALAR}),
        "runner": SCALAR,
        "max_todo_dispatch": SCALAR,
    }
)
_DEPLOYMENT_INPUT = ClosedMapping({"channel": SCALAR, "pinned_minor": SCALAR})
_EXPERIMENT_INPUT = ClosedMapping({"name": SCALAR, "agents": InputList(SCALAR), "adapters": InputList(SCALAR)})

MACHINE_CONFIG_INPUT = ClosedMapping(
    {
        "kind": SCALAR,
        "computer": ClosedMapping(
            {
                "name": SCALAR,
                "user": SCALAR,
                "role": SCALAR,
                "timezone": SCALAR,
                "default_working_dir": SCALAR,
                "help_desk_dir": SCALAR,
                "is_master": SCALAR,
                "trusted_dirs": InputList(_TRUSTED_DIRECTORY_INPUT),
                "host": SCALAR,
                "is_ingress_node": SCALAR,
            }
        ),
        "remote_computers": REMOTE_COMPUTERS_INPUT,
        "redis": ClosedMapping(
            {
                "url": SCALAR,
                "password": SCALAR,
                "max_connections": SCALAR,
                "socket_timeout": SCALAR,
                "message_stream_maxlen": SCALAR,
                "output_stream_maxlen": SCALAR,
                "output_stream_ttl": SCALAR,
            }
        ),
        "telegram": ClosedMapping(
            {
                "enabled": SCALAR,
                "bot_token": SCALAR,
                "alert_username": SCALAR,
                "alert_chat_id": SCALAR,
                "qos": _TELEGRAM_QOS_INPUT,
            }
        ),
        "discord": ClosedMapping(
            {
                "enabled": SCALAR,
                "token": SCALAR,
                "guild_id": SCALAR,
                "qos": _MODE_QOS_INPUT,
            }
        ),
        "whatsapp": ClosedMapping(
            {
                "enabled": SCALAR,
                "phone_number_id": SCALAR,
                "access_token": SCALAR,
                "webhook_secret": SCALAR,
                "verify_token": SCALAR,
                "template_name": SCALAR,
                "template_language": SCALAR,
                "business_number": SCALAR,
                "api_version": SCALAR,
                "qos": _MODE_QOS_INPUT,
            }
        ),
        "creds": ClosedMapping(
            {
                "telegram": ClosedMapping({"user_name": SCALAR, "user_id": SCALAR}),
                "whatsapp": ClosedMapping({"phone_number": SCALAR}),
            }
        ),
        "terminal": ClosedMapping({"strip_ansi": SCALAR}),
        "hook_outbox": HOOK_OUTBOX_INPUT,
        "api": API_INPUT,
        "daemon": DAEMON_INPUT,
        "tts": _TTS_INPUT,
        "stt": _STT_INPUT,
        "chiptunes": CHIPTUNES_INPUT,
        "process_janitor": _PROCESS_JANITOR_INPUT,
        "workflow": _WORKFLOW_INPUT,
        "deployment": _DEPLOYMENT_INPUT,
        "summarizer": SUMMARIZER_INPUT,
        "experiments": InputList(_EXPERIMENT_INPUT),
        "agents": OPEN,
        "email": ClosedMapping(
            {
                "enabled": SCALAR,
                "smtp_username": SCALAR,
                "smtp_key": SCALAR,
                "email_from": SCALAR,
                "reply_to": SCALAR,
                "smtp_relay": SCALAR,
            }
        ),
        "backup": ClosedMapping(
            {
                "aws_access_key_id": SCALAR,
                "aws_secret_access_key": SCALAR,
                "aws_s3_host": SCALAR,
                "aws_s3_region": SCALAR,
                "aws_s3_bucket": SCALAR,
                "backup_prefix": SCALAR,
            }
        ),
        "database_url": SCALAR,
    }
)
EXPERIMENTS_FILE_INPUT = ClosedMapping({"experiments": InputList(_EXPERIMENT_INPUT)})
