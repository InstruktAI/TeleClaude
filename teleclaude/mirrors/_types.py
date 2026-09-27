"""Recursive JSON values used by mirror persistence models."""

from __future__ import annotations

type JsonScalar = str | int | float | bool | None
type JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
