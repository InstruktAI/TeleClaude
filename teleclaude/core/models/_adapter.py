"""Adapter metadata types for TeleClaude sessions.

Per-platform dataclasses store adapter-specific state. Each has from_dict/to_dict
for round-tripping through the origin_metadata JSON column. The container classes
(SessionAdapterMetadata, UiAdapterMetadata, TransportAdapterMetadata) are kept
temporarily for migration but will be removed.
"""

import json
from collections.abc import Iterator, Mapping
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
class PeerInfo:
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
    bot_username: str | None = None


def _int_or_none(value: object) -> int | None:
    """Coerce to int if possible."""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _str_or_none(value: object) -> str | None:
    """Coerce to str if not None."""
    return str(value) if value is not None else None


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

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "TelegramAdapterMetadata":  # guard: loose-dict
        """Deserialize from a dict with type coercion."""
        footer = raw.get("footer_message_id") or raw.get("threaded_footer_message_id")
        return cls(
            topic_id=_int_or_none(raw.get("topic_id")),
            output_message_id=_str_or_none(raw.get("output_message_id")),
            footer_message_id=_str_or_none(footer),
            output_suppressed=bool(raw.get("output_suppressed", False)),
            parse_mode=str(raw["parse_mode"]) if raw.get("parse_mode") else None,
            char_offset=int(raw.get("char_offset", 0)),
            user_id=_int_or_none(raw.get("user_id")),
            badge_sent=bool(raw.get("badge_sent", False)),
        )

    def to_dict(self) -> dict[str, object]:  # guard: loose-dict - JSON serialization output
        """Serialize to dict, excluding None fields."""
        return dict(asdict_exclude_none(self))


@dataclass
class DiscordAdapterMetadata:
    """Discord-specific adapter metadata."""

    user_id: str | None = None
    guild_id: int | None = None
    channel_id: int | None = None
    thread_id: int | None = None
    all_sessions_thread_id: int | None = None
    output_message_id: str | None = None
    thread_topper_message_id: str | None = None
    status_message_id: str | None = None
    badge_sent: bool = False
    char_offset: int = 0

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "DiscordAdapterMetadata":  # guard: loose-dict
        """Deserialize from a dict with type coercion."""
        return cls(
            user_id=_str_or_none(raw.get("user_id")),
            guild_id=_int_or_none(raw.get("guild_id")),
            channel_id=_int_or_none(raw.get("channel_id")),
            thread_id=_int_or_none(raw.get("thread_id")),
            all_sessions_thread_id=_int_or_none(raw.get("all_sessions_thread_id")),
            output_message_id=_str_or_none(raw.get("output_message_id")),
            thread_topper_message_id=_str_or_none(raw.get("thread_topper_message_id")),
            status_message_id=_str_or_none(raw.get("status_message_id")),
            badge_sent=bool(raw.get("badge_sent", False)),
            char_offset=int(raw.get("char_offset", 0)),
        )

    def to_dict(self) -> dict[str, object]:  # guard: loose-dict - JSON serialization output
        """Serialize to dict, excluding None fields."""
        return dict(asdict_exclude_none(self))


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

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "WhatsAppAdapterMetadata":  # guard: loose-dict
        """Deserialize from a dict with type coercion."""
        return cls(
            phone_number=_str_or_none(raw.get("phone_number")),
            conversation_id=_str_or_none(raw.get("conversation_id")),
            output_message_id=_str_or_none(raw.get("output_message_id")),
            badge_sent=bool(raw.get("badge_sent", False)),
            char_offset=int(raw.get("char_offset", 0)),
            last_customer_message_at=_str_or_none(raw.get("last_customer_message_at")),
            last_received_message_id=_str_or_none(raw.get("last_received_message_id")),
            closed=bool(raw.get("closed", False)),
        )

    def to_dict(self) -> dict[str, object]:  # guard: loose-dict - JSON serialization output
        """Serialize to dict, excluding None fields."""
        return dict(asdict_exclude_none(self))


@dataclass
class RedisTransportMetadata:
    """Redis-specific adapter metadata."""

    channel_id: str | None = None
    output_stream: str | None = None
    target_computer: str | None = None
    native_session_id: str | None = None
    project_path: str | None = None
    last_checkpoint_time: str | None = None
    title: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "RedisTransportMetadata":  # guard: loose-dict
        """Deserialize from a dict with type coercion."""
        return cls(
            channel_id=_str_or_none(raw.get("channel_id")),
            output_stream=_str_or_none(raw.get("output_stream")),
            target_computer=_str_or_none(raw.get("target_computer")),
            native_session_id=_str_or_none(raw.get("native_session_id")),
            project_path=_str_or_none(raw.get("project_path")),
            last_checkpoint_time=_str_or_none(raw.get("last_checkpoint_time")),
            title=_str_or_none(raw.get("title")),
        )

    def to_dict(self) -> dict[str, object]:  # guard: loose-dict - JSON serialization output
        """Serialize to dict, excluding None fields."""
        return dict(asdict_exclude_none(self))


@dataclass
class WebOriginMetadata(Mapping[str, object]):
    """Web-specific origin metadata for identity resolution."""

    email: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "WebOriginMetadata":  # guard: loose-dict
        """Deserialize from a dict."""
        return cls(email=_str_or_none(raw.get("email")))

    def to_dict(self) -> dict[str, object]:  # guard: loose-dict - JSON serialization output
        """Serialize to dict, excluding None fields."""
        return dict(asdict_exclude_none(self))

    def __getitem__(self, key: str) -> object:
        d = self.to_dict()
        return d[key]

    def __len__(self) -> int:
        return len(self.to_dict())

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())


@dataclass
class TerminalOriginMetadata(Mapping[str, object]):
    """Terminal-specific origin metadata for identity resolution."""

    email: str | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> "TerminalOriginMetadata":  # guard: loose-dict
        """Deserialize from a dict."""
        return cls(email=_str_or_none(raw.get("email")))

    def to_dict(self) -> dict[str, object]:  # guard: loose-dict - JSON serialization output
        """Serialize to dict, excluding None fields."""
        return dict(asdict_exclude_none(self))

    def __getitem__(self, key: str) -> object:
        d = self.to_dict()
        return d[key]

    def __len__(self) -> int:
        return len(self.to_dict())

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())


# ---------------------------------------------------------------------------
# Container classes — MIGRATION SHIM
#
# These exist only so existing code that accesses
# session.adapter_metadata.get_ui().get_telegram() continues to work during
# the migration to origin_metadata. They will be removed once all adapters
# read/write through origin_metadata directly.
# ---------------------------------------------------------------------------


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

    @property
    def telegram(self) -> TelegramAdapterMetadata | None:
        """Return Telegram metadata without creating a default container."""
        return self._telegram

    @property
    def discord(self) -> DiscordAdapterMetadata | None:
        """Return Discord metadata without creating a default container."""
        return self._discord

    @property
    def whatsapp(self) -> WhatsAppAdapterMetadata | None:
        """Return WhatsApp metadata without creating a default container."""
        return self._whatsapp


@dataclass
class TransportAdapterMetadata:
    """Metadata container for Transport adapters."""

    _redis: RedisTransportMetadata | None = None

    def get_redis(self) -> RedisTransportMetadata:
        """Get Redis metadata, initializing if missing."""
        if self._redis is None:
            self._redis = RedisTransportMetadata()
        return self._redis

    @property
    def redis(self) -> RedisTransportMetadata | None:
        """Return Redis metadata without creating a default container."""
        return self._redis


@dataclass
class SessionAdapterMetadata:
    """Typed metadata container for all adapters.

    MIGRATION SHIM — will be removed when all adapters use origin_metadata.
    """

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
        """Serialize to JSON string, excluding None fields."""
        data: dict[str, JsonValue] = {}
        ui_metadata = self.get_ui()
        transport_metadata = self.get_transport()

        if ui_metadata.telegram:
            data["telegram"] = ui_metadata.telegram.to_dict()
        if ui_metadata.discord:
            data["discord"] = ui_metadata.discord.to_dict()
        if ui_metadata.whatsapp:
            data["whatsapp"] = ui_metadata.whatsapp.to_dict()
        if transport_metadata.redis:
            data["redis"] = transport_metadata.redis.to_dict()

        return json.dumps(data)

    @classmethod
    def from_json(cls, raw: str) -> "SessionAdapterMetadata":
        """Deserialize from JSON string."""
        data_obj: object = json.loads(raw)
        telegram_metadata: TelegramAdapterMetadata | None = None
        discord_metadata: DiscordAdapterMetadata | None = None
        whatsapp_metadata: WhatsAppAdapterMetadata | None = None
        redis_metadata: RedisTransportMetadata | None = None

        if isinstance(data_obj, dict):
            tg_raw = data_obj.get("telegram")
            if isinstance(tg_raw, dict):
                telegram_metadata = TelegramAdapterMetadata.from_dict(tg_raw)

            discord_raw = data_obj.get("discord")
            if isinstance(discord_raw, dict):
                discord_metadata = DiscordAdapterMetadata.from_dict(discord_raw)

            whatsapp_raw = data_obj.get("whatsapp")
            if isinstance(whatsapp_raw, dict):
                whatsapp_metadata = WhatsAppAdapterMetadata.from_dict(whatsapp_raw)

            redis_raw = data_obj.get("redis")
            if isinstance(redis_raw, dict):
                redis_metadata = RedisTransportMetadata.from_dict(redis_raw)

        ui_metadata = UiAdapterMetadata(
            _telegram=telegram_metadata, _discord=discord_metadata, _whatsapp=whatsapp_metadata
        )
        transport_metadata = TransportAdapterMetadata(_redis=redis_metadata)
        return cls(_ui=ui_metadata, _transport=transport_metadata)
