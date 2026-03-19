"""Shared JSON payload readers for hook entrypoints."""

from __future__ import annotations

import json
import sys
from typing import cast

type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


def read_stdin_payload() -> tuple[str, JsonObject]:
    """Read a JSON object from stdin when the process is piped."""
    raw_input = ""
    data: JsonObject = {}
    if not sys.stdin.isatty():
        raw_input = sys.stdin.read()
        if raw_input.strip():
            parsed = json.loads(raw_input)
            if not isinstance(parsed, dict):
                raise ValueError("Hook stdin payload must be a JSON object")
            data = cast(JsonObject, parsed)
    return raw_input, data
