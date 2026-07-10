"""Strict JSONC parsing for TeleClaude MCP registry files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

type JsonObject = dict[str, object]  # guard: loose-dict - JSON registry objects are schema validated.


class JsoncError(ValueError):
    """Raised when a JSONC file cannot be parsed as a registry object."""


def load_jsonc_object(path: Path, *, required: bool) -> JsonObject:
    """Load a JSONC object from ``path``.

    Comments and trailing commas are accepted; every other JSON syntax rule is
    preserved so bad registry files fail loudly at the config boundary.
    """
    if not path.exists():
        if required:
            raise JsoncError(f"Missing MCP registry file at {path}")
        return {}
    raw = path.read_text(encoding="utf-8")
    try:
        parsed = json.loads(_strip_trailing_commas(_strip_comments(raw)))
    except json.JSONDecodeError as exc:
        raise JsoncError(f"Invalid JSONC at {path}:{exc.lineno}:{exc.colno}: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise JsoncError(f"Invalid JSONC at {path}: top-level value must be an object.")
    return cast(JsonObject, parsed)


def _strip_comments(text: str) -> str:
    result: list[str] = []
    in_string = False
    escape = False
    index = 0
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if in_string:
            result.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue
        if char == "/" and next_char == "/":
            while index < len(text) and text[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and next_char == "*":
            result.extend("  ")
            index += 2
            while index < len(text) - 1 and not (text[index] == "*" and text[index + 1] == "/"):
                result.append("\n" if text[index] in "\r\n" else " ")
                index += 1
            if index < len(text) - 1:
                result.extend("  ")
                index += 2
            continue
        result.append(char)
        index += 1
    return "".join(result)


def _strip_trailing_commas(text: str) -> str:
    result: list[str] = []
    in_string = False
    escape = False
    index = 0
    while index < len(text):
        char = text[index]
        if in_string:
            result.append(char)
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            index += 1
            continue
        if char == '"':
            in_string = True
            result.append(char)
            index += 1
            continue
        if char == ",":
            lookahead = index + 1
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead < len(text) and text[lookahead] in "}]":
                index += 1
                continue
        result.append(char)
        index += 1
    return "".join(result)
