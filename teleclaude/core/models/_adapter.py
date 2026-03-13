"""Adapter metadata types for TeleClaude sessions."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from teleclaude.types import SystemStats

from ._types import JsonValue, asdict_exclude_none


class AdapterType(str, Enum):
    """Adapter type enum."""

    TELEGRAM = "telegram"
    DISCORD = "discord"
    WHATSAPP = "whatsapp"
    REDIS = "redis"


@dataclass
class PeerInfo:  # pylint: disable=too-many-instance-attributes
    """Information about a discovered peer computer."""

    name: str
    status: str  # "online" or "offline"
    last_seen: datetime
    adapter_type: str
    user: str | None = None
    host: str | None = None
    ip: str | None = None
    role: str | None = None
    system_stats: SystemStats | None = None
    tmux_binary: str | None = None


@dataclass
class TelegramAdapterMetadata:
    """Telegram-specific adapter metadata."""

    topic_id: int | None = None
    output_message_id: str | None = None
    footer_message_id: str | None = None
    output_suppressed: bool = False
    parse_mode: str | None = None
    char_offset: int = 0
    user_id: int | None = None
    badge_sent: bool = False


@dataclass
class DiscordAdapterMetadata:
    """Discord-specific adapter metadata."""

    user_id: str | None = None
    guild_id: int | None = None
    channel_id: int | None = None
    thread_id: int | None = None
    all_sessions_thread_id: int | None = None
    output_message_id: str | None = None
    thread_topper_message_id: str | None = None  # Starter metadata message in thread
    status_message_id: str | None = None  # Editable status message per thread (R3)
    badge_sent: bool = False
    char_offset: int = 0


@dataclass
class WhatsAppAdapterMetadata:
    """WhatsApp-specific adapter metadata."""

    phone_number: str | None = None
    conversation_id: str | None = None
    output_message_id: str | None = None
    badge_sent: bool = False
    char_offset: int = 0
    last_customer_message_at: str | None = None
    last_received_message_id: str | None = None
    closed: bool = False


@dataclass
class UiAdapterMetadata:
    """Metadata container for UI adapters."""

    _telegram: TelegramAdapterMetadata | None = None
    _discord: DiscordAdapterMetadata | None = None
    _whatsapp: WhatsAppAdapterMetadata | None = None

    def get_telegram(self) -> TelegramAdapterMetadata:
        """Get Telegram metadata, initializing if missing."""
        if self._telegram is None:
            self._telegram = TelegramAdapterMetadata()
        return self._telegram

    def get_discord(self) -> DiscordAdapterMetadata:
        """Get Discord metadata, initializing if missing."""
        if self._discord is None:
            self._discord = DiscordAdapterMetadata()
        return self._discord

    def get_whatsapp(self) -> WhatsAppAdapterMetadata:
        """Get WhatsApp metadata, initializing if missing."""
        if self._whatsapp is None:
            self._whatsapp = WhatsAppAdapterMetadata()
        return self._whatsapp


@dataclass
class RedisTransportMetadata:  # pylint: disable=too-many-instance-attributes
    """Redis-specific adapter metadata."""

    channel_id: str | None = None
    output_stream: str | None = None
    target_computer: str | None = None
    native_session_id: str | None = None
    project_path: str | None = None
    last_checkpoint_time: str | None = None
    title: str | None = None
    channel_metadata: str | None = None  # JSON string


@dataclass
class TransportAdapterMetadata:
    """Metadata container for Transport adapters."""

    _redis: RedisTransportMetadata | None = None

    def get_redis(self) -> RedisTransportMetadata:
        """Get Redis metadata, initializing if missing."""
        if self._redis is None:
            self._redis = RedisTransportMetadata()
        return self._redis


@dataclass
class SessionAdapterMetadata:
    """Typed metadata container for all adapters."""

    _ui: UiAdapterMetadata = field(default_factory=UiAdapterMetadata)
    _transport: TransportAdapterMetadata = field(default_factory=TransportAdapterMetadata)

    def __init__(
        self,
        telegram: TelegramAdapterMetadata | None = None,
        discord: DiscordAdapterMetadata | None = None,
        whatsapp: WhatsAppAdapterMetadata | None = None,
        redis: RedisTransportMetadata | None = None,
        _ui: UiAdapterMetadata | None = None,
        _transport: TransportAdapterMetadata | None = None,
    ) -> None:
        """Initialize with backward compatibility for adapter shorthand args."""
        if _ui is not None:
            self._ui = _ui
        else:
            self._ui = UiAdapterMetadata(_telegram=telegram, _discord=discord, _whatsapp=whatsapp)

        if _transport is not None:
            self._transport = _transport
        else:
            self._transport = TransportAdapterMetadata(_redis=redis)

    def get_ui(self) -> UiAdapterMetadata:
        """Get UI adapter metadata container."""
        return self._ui

    def get_transport(self) -> TransportAdapterMetadata:
        """Get Transport adapter metadata container."""
        return self._transport

    def to_json(self) -> str:
        """Serialize to JSON string, excluding None fields.

        Flattens adapters back to root keys for backward compatibility.
        """
        # manual dict construction to preserve root keys
        data: dict[str, JsonValue] = {}

        # UI Adapters (flattened)
        if self._ui._telegram:
            data["telegram"] = asdict_exclude_none(self._ui._telegram)
        if self._ui._discord:
            data["discord"] = asdict_exclude_none(self._ui._discord)
        if self._ui._whatsapp:
            data["whatsapp"] = asdict_exclude_none(self._ui._whatsapp)

        # Transport Adapters (flattened)
        if self._transport._redis:
            data["redis"] = asdict_exclude_none(self._transport._redis)

        return json.dumps(data)

    @classmethod
    def from_json(cls, raw: str) -> "SessionAdapterMetadata":
        """Deserialize from JSON string, filtering unknown fields per adapter."""
        data_obj: object = json.loads(raw)
        telegram_metadata: TelegramAdapterMetadata | None = None
        discord_metadata: DiscordAdapterMetadata | None = None
        whatsapp_metadata: WhatsAppAdapterMetadata | None = None
        redis_metadata: RedisTransportMetadata | None = None

        if isinstance(data_obj, dict):
            tg_raw = data_obj.get("telegram")
            if isinstance(tg_raw, dict):
                topic_id_val: object = tg_raw.get("topic_id")
                output_msg_val: object = tg_raw.get("output_message_id")
                footer_val: object = tg_raw.get("footer_message_id") or tg_raw.get("threaded_footer_message_id")
                topic_id: int | None = None
                if isinstance(topic_id_val, int):
                    topic_id = topic_id_val
                elif isinstance(topic_id_val, str) and topic_id_val.isdigit():
                    topic_id = int(topic_id_val)
                output_message_id = str(output_msg_val) if output_msg_val is not None else None
                footer_message_id = str(footer_val) if footer_val is not None else None
                output_suppressed = bool(tg_raw.get("output_suppressed", False))
                parse_mode = str(tg_raw.get("parse_mode")) if tg_raw.get("parse_mode") else None
                char_offset = int(tg_raw.get("char_offset", 0))
                tg_user_id_val: object = tg_raw.get("user_id")
                tg_user_id: int | None = None
                if isinstance(tg_user_id_val, int):
                    tg_user_id = tg_user_id_val
                elif isinstance(tg_user_id_val, str) and tg_user_id_val.isdigit():
                    tg_user_id = int(tg_user_id_val)
                telegram_metadata = TelegramAdapterMetadata(
                    topic_id=topic_id,
                    output_message_id=output_message_id,
                    footer_message_id=footer_message_id,
                    output_suppressed=output_suppressed,
                    parse_mode=parse_mode,
                    char_offset=char_offset,
                    user_id=tg_user_id,
                    badge_sent=bool(tg_raw.get("badge_sent", False)),
                )

            discord_raw = data_obj.get("discord")
            if isinstance(discord_raw, dict):

                def _get_int_or_none(key: str) -> int | None:
                    value = discord_raw.get(key)
                    if isinstance(value, int):
                        return value
                    if isinstance(value, str) and value.isdigit():
                        return int(value)
                    return None

                raw_user_id = discord_raw.get("user_id")
                user_id = str(raw_user_id) if raw_user_id is not None else None
                raw_output_msg = discord_raw.get("output_message_id")
                discord_output_message_id = str(raw_output_msg) if raw_output_msg is not None else None
                raw_topper_msg = discord_raw.get("thread_topper_message_id")
                discord_topper_message_id = str(raw_topper_msg) if raw_topper_msg is not None else None
                raw_status_msg = discord_raw.get("status_message_id")
                discord_status_message_id = str(raw_status_msg) if raw_status_msg is not None else None
                discord_metadata = DiscordAdapterMetadata(
                    user_id=user_id,
                    guild_id=_get_int_or_none("guild_id"),
                    channel_id=_get_int_or_none("channel_id"),
                    thread_id=_get_int_or_none("thread_id"),
                    all_sessions_thread_id=_get_int_or_none("all_sessions_thread_id"),
                    output_message_id=discord_output_message_id,
                    thread_topper_message_id=discord_topper_message_id,
                    status_message_id=discord_status_message_id,
                    badge_sent=bool(discord_raw.get("badge_sent", False)),
                    char_offset=int(discord_raw.get("char_offset", 0)),
                )

            whatsapp_raw = data_obj.get("whatsapp")
            if isinstance(whatsapp_raw, dict):

                def _get_wa_str(key: str) -> str | None:
                    val = whatsapp_raw.get(key)
                    return str(val) if val is not None else None

                whatsapp_metadata = WhatsAppAdapterMetadata(
                    phone_number=_get_wa_str("phone_number"),
                    conversation_id=_get_wa_str("conversation_id"),
                    output_message_id=_get_wa_str("output_message_id"),
                    badge_sent=bool(whatsapp_raw.get("badge_sent", False)),
                    char_offset=int(whatsapp_raw.get("char_offset", 0)),
                    last_customer_message_at=_get_wa_str("last_customer_message_at"),
                    last_received_message_id=_get_wa_str("last_received_message_id"),
                    closed=bool(whatsapp_raw.get("closed", False)),
                )

            redis_raw = data_obj.get("redis")
            if isinstance(redis_raw, dict):

                def _get_str(key: str) -> str | None:
                    val = redis_raw.get(key)
                    return str(val) if val is not None else None

                channel_meta_val = redis_raw.get("channel_metadata")
                channel_meta_str: str | None
                if isinstance(channel_meta_val, dict):
                    channel_meta_str = json.dumps(channel_meta_val)
                elif channel_meta_val is not None:
                    channel_meta_str = str(channel_meta_val)
                else:
                    channel_meta_str = None

                redis_metadata = RedisTransportMetadata(
                    channel_id=_get_str("channel_id"),
                    output_stream=_get_str("output_stream"),
                    target_computer=_get_str("target_computer"),
                    native_session_id=_get_str("native_session_id"),
                    project_path=_get_str("project_path"),
                    last_checkpoint_time=_get_str("last_checkpoint_time"),
                    title=_get_str("title"),
                    channel_metadata=channel_meta_str,
                )

        # Reconstruct hierarchy
        ui_metadata = UiAdapterMetadata(
            _telegram=telegram_metadata, _discord=discord_metadata, _whatsapp=whatsapp_metadata
        )
        transport_metadata = TransportAdapterMetadata(_redis=redis_metadata)
        return cls(_ui=ui_metadata, _transport=transport_metadata)
