from dataclasses import asdict
from typing import ClassVar, NotRequired, Protocol, TypedDict, cast

# JSON-serializable types for database storage
type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list[JsonValue] | dict[str, JsonValue]
type JsonDict = dict[str, JsonValue]


class TelegramOriginSection(TypedDict):
    """Telegram-specific origin section keys."""

    user_id: NotRequired[int | str | None]
    telegram_user_id: NotRequired[int | str | None]
    chat_type: NotRequired[str | None]
    platform: NotRequired[str | None]


class DiscordOriginSection(TypedDict):
    """Discord-specific origin section keys."""

    user_id: NotRequired[str | None]
    discord_user_id: NotRequired[str | None]
    platform: NotRequired[str | None]


class WhatsAppOriginSection(TypedDict):
    """WhatsApp-specific origin section keys."""

    phone_number: NotRequired[str | None]
    platform: NotRequired[str | None]


class TerminalOriginSection(TypedDict):
    """Terminal-specific origin section keys."""

    email: NotRequired[str | None]
    platform: NotRequired[str | None]


class WebOriginSection(TypedDict):
    """Web-specific origin section keys."""

    email: NotRequired[str | None]
    platform: NotRequired[str | None]


class PeerBundleSegmentWireDict(TypedDict):
    """Cross-computer wire shape for one durable peer-bundle segment.

    Carried on `ProcessMessageCommand.peer_bundle_segments` for a
    cross-computer bundle delivery; decoded back into a typed
    `PeerBundleSegmentInput` by the receiving computer.
    """

    original_source_session_id: str
    author_kind: str
    author_display: str
    author_agent_runtime: str | None
    author_thinking_mode: str | None
    author_machine_role: str | None
    author_job_role: str | None
    occurred_at: str
    body: str


class SessionOriginMetadata(TypedDict):
    """Type-safe schema representing the merged/accumulated session origin metadata."""

    platform: NotRequired[str | None]
    email: NotRequired[str | None]
    user_id: NotRequired[int | str | None]
    telegram_user_id: NotRequired[int | str | None]
    discord_user_id: NotRequired[str | None]
    phone_number: NotRequired[str | None]
    chat_type: NotRequired[str | None]

    # Nested platform sections
    telegram: NotRequired[dict[str, object] | None]  # guard: loose-dict
    discord: NotRequired[dict[str, object] | None]  # guard: loose-dict
    whatsapp: NotRequired[dict[str, object] | None]  # guard: loose-dict
    redis: NotRequired[dict[str, object] | None]  # guard: loose-dict


class _DataclassInstance(Protocol):
    __dataclass_fields__: ClassVar[dict[str, object]]  # guard: loose-dict - dataclass introspection interface


def asdict_exclude_none(obj: object) -> JsonDict:
    """Convert dataclass to dict, recursively excluding None values."""

    # Handle already-dict objects (defensive)
    def _exclude_none(data: object) -> JsonValue:
        """Recursively exclude None values from dicts and lists."""
        if isinstance(data, dict):
            result: dict[str, JsonValue] = {}
            for key, value in data.items():
                if value is None:
                    continue
                result[str(key)] = _exclude_none(value)
            return result
        if isinstance(data, list):
            return [_exclude_none(item) for item in data]
        return cast(JsonPrimitive, data)

    if isinstance(obj, dict):
        return cast(JsonDict, _exclude_none(obj))

    # asdict needs a dataclass instance
    if not hasattr(obj, "__dataclass_fields__"):
        raise TypeError("asdict_exclude_none expects a dataclass instance or dict")
    result = cast(JsonDict, asdict(cast(_DataclassInstance, obj)))
    return cast(JsonDict, _exclude_none(result))
