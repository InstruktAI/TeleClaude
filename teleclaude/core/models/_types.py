from dataclasses import asdict
from typing import ClassVar, NotRequired, Protocol, TypedDict, cast

# JSON-serializable types for database storage
type JsonPrimitive = str | int | float | bool | None
type JsonValue = JsonPrimitive | list[JsonValue] | dict[str, JsonValue]
type JsonDict = dict[str, JsonValue]
_JSON_OBJECT_KEY_ERROR = "JSON object keys must be strings"
_JSON_VALUE_ERROR = "Value is not JSON-compatible"
_INT_COERCION_ERROR_FORMAT = "int() argument must be a string, a bytes-like object or a real number, not '{}'"


def to_json_value(value: object) -> JsonValue:
    """Copy a Python value into the recursively JSON-compatible type."""
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, list):
        return [to_json_value(item) for item in value]
    if isinstance(value, dict):
        result: JsonDict = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(_JSON_OBJECT_KEY_ERROR)
            result[key] = to_json_value(item)
        return result
    raise TypeError(_JSON_VALUE_ERROR)


def to_json_dict(value: object) -> JsonDict:
    """Copy a Python object into a recursively JSON-compatible dictionary."""
    if not isinstance(value, dict):
        raise TypeError(_JSON_VALUE_ERROR)
    result: JsonDict = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise TypeError(_JSON_OBJECT_KEY_ERROR)
        result[key] = to_json_value(item)
    return result


def json_int(value: object) -> int:
    """Convert a JSON scalar with the same coercion accepted by ``int``."""
    if isinstance(value, (str, int, float)):
        return int(value)
    raise TypeError(_INT_COERCION_ERROR_FORMAT.format(type(value).__name__))


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


CONFINEMENT_SECTION = "confinement"
CONFINEMENT_PROFILE_KEY = "profile"


class SessionConfinementSection(TypedDict):
    """Root origin-metadata section recording the launch confinement chosen at creation."""

    profile: str


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
    attention_observation: NotRequired[dict[str, object] | None]  # guard: loose-dict - remote distress evidence
    inferred_stall_evidence: NotRequired[dict[str, object] | None]  # guard: loose-dict - remote watchdog evidence
    confinement: NotRequired[SessionConfinementSection | None]


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
    result = cast(JsonDict, asdict(cast(_DataclassInstance, obj)))  # pyright: ignore[reportArgumentType]  # typeshed requires invariant Field[Any] metadata after the dataclass check above
    return cast(JsonDict, _exclude_none(result))
