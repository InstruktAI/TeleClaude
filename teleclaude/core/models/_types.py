"""Shared JSON type aliases and utility functions for models."""

from dataclasses import asdict
from typing import ClassVar, Protocol, cast

# JSON-serializable types for database storage
JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
JsonDict = dict[str, JsonValue]


class _DataclassInstance(Protocol):
    __dataclass_fields__: ClassVar[dict[str, object]]


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
