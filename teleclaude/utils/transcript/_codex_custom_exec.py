"""Structured extraction for Codex custom-exec transport envelopes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

_CUSTOM_EXEC_NAME = "exec"
_CUSTOM_EXEC_COMMAND = "tools.exec_command"
_CUSTOM_APPLY_PATCH_COMMAND = "tools.apply_patch"
_EXEC_COMMAND_TOOL_NAME: Literal["exec_command"] = "exec_command"
_APPLY_PATCH_TOOL_NAME: Literal["apply_patch"] = "apply_patch"
_WAIT_TOOL_NAME = "wait"
_CMD_PROPERTY_NAME = "cmd"
_CELL_ID_PROPERTY_NAME = "cell_id"
_CELL_ID_OUTPUT_PREFIX = "Script running with cell ID "
_JS_OPEN_PAREN = "("
_JS_CLOSE_PAREN = ")"
_JS_OPEN_BRACE = "{"
_JS_CLOSE_BRACE = "}"
_JS_OPEN_BRACKET = "["
_JS_CLOSE_BRACKET = "]"
_JS_COMMA = ","
_JS_COLON = ":"
_JS_EQUALS = "="
_JS_BACKSLASH = "\\"
_JS_SINGLE_QUOTE = "'"
_JS_DOUBLE_QUOTE = '"'
_JS_QUOTE_CHARS = {_JS_SINGLE_QUOTE, _JS_DOUBLE_QUOTE}
_JS_ESCAPE_TRANSLATIONS = {"n": "\n", "r": "\r", "t": "\t"}
_JS_LINE_COMMENT = "//"
_JS_BLOCK_COMMENT_START = "/*"
_JS_BLOCK_COMMENT_END = "*/"
_NEWLINE = "\n"
_EMPTY_STRING = ""
_UNDERSCORE = "_"
_CALL_ID_FIELD = "call_id"
_INPUT_FIELD = "input"
_NAME_FIELD = "name"
_OUTPUT_FIELD = "output"
_UNKNOWN_TOOL_NAME = "unknown"

_NestedCustomExecToolName = Literal["exec_command", "apply_patch"]


def _read_js_quoted_string(source: str, start: int) -> tuple[str, int] | None:
    """Read one JavaScript string literal without interpreting surrounding code."""
    if start >= len(source) or source[start] not in _JS_QUOTE_CHARS:
        return None
    quote = source[start]
    characters: list[str] = []
    index = start + 1
    while index < len(source):
        character = source[index]
        if character == quote:
            return _EMPTY_STRING.join(characters), index + 1
        if character == _JS_BACKSLASH and index + 1 < len(source):
            escaped = source[index + 1]
            characters.append(_JS_ESCAPE_TRANSLATIONS.get(escaped, escaped))
            index += 2
            continue
        characters.append(character)
        index += 1
    return None


def _skip_js_whitespace(source: str, start: int) -> int:
    """Return the first non-whitespace source offset."""
    index = start
    while index < len(source) and source[index].isspace():
        index += 1
    return index


def _find_js_object_end(source: str, start: int) -> int | None:
    """Find the matching close brace for one JavaScript object literal."""
    if start >= len(source) or source[start] != _JS_OPEN_BRACE:
        return None
    depth = 0
    index = start
    while index < len(source):
        character = source[index]
        if character in _JS_QUOTE_CHARS:
            parsed_string = _read_js_quoted_string(source, index)
            if parsed_string is None:
                return None
            _value, index = parsed_string
            continue
        if character == _JS_OPEN_BRACE:
            depth += 1
        elif character == _JS_CLOSE_BRACE:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return None


def _skip_js_property_value(source: str, start: int) -> int:
    """Advance to the next top-level object-property delimiter."""
    depth = 0
    index = start
    while index < len(source):
        character = source[index]
        if character in _JS_QUOTE_CHARS:
            parsed_string = _read_js_quoted_string(source, index)
            if parsed_string is None:
                return len(source)
            _value, index = parsed_string
            continue
        if character in {_JS_OPEN_BRACE, _JS_OPEN_PAREN, _JS_OPEN_BRACKET}:
            depth += 1
        elif character in {_JS_CLOSE_BRACE, _JS_CLOSE_PAREN, _JS_CLOSE_BRACKET}:
            if depth == 0:
                return index
            depth -= 1
        elif character == _JS_COMMA and depth == 0:
            return index + 1
        index += 1
    return index


def _extract_cmd_from_exec_object(source: str) -> str | None:
    """Read a statically quoted cmd property from one exec-command object."""
    index = 1
    while index < len(source) - 1:
        index = _skip_js_whitespace(source, index)
        if index < len(source) and source[index] == _JS_COMMA:
            index += 1
            continue
        if index >= len(source) - 1:
            return None
        if source[index] in _JS_QUOTE_CHARS:
            parsed_key = _read_js_quoted_string(source, index)
            if parsed_key is None:
                return None
            key, index = parsed_key
        else:
            key_start = index
            while index < len(source) and (source[index].isalnum() or source[index] == _UNDERSCORE):
                index += 1
            key = source[key_start:index]
        index = _skip_js_whitespace(source, index)
        if index >= len(source) or source[index] != _JS_COLON:
            return None
        value_start = _skip_js_whitespace(source, index + 1)
        if key == _CMD_PROPERTY_NAME:
            parsed_value = _read_js_quoted_string(source, value_start)
            return parsed_value[0] if parsed_value is not None else None
        index = _skip_js_property_value(source, value_start)
    return None


def _find_next_tool_invocation(source: str, start: int, command: str) -> int | None:
    """Find one nested tool call in JavaScript code, excluding strings and comments."""
    index = start
    while index < len(source):
        if source[index] in _JS_QUOTE_CHARS:
            parsed_string = _read_js_quoted_string(source, index)
            if parsed_string is None:
                return None
            _value, index = parsed_string
            continue
        if source.startswith(_JS_LINE_COMMENT, index):
            line_end = source.find(_NEWLINE, index + len(_JS_LINE_COMMENT))
            index = len(source) if line_end < 0 else line_end + 1
            continue
        if source.startswith(_JS_BLOCK_COMMENT_START, index):
            comment_end = source.find(_JS_BLOCK_COMMENT_END, index + len(_JS_BLOCK_COMMENT_START))
            if comment_end < 0:
                return None
            index = comment_end + len(_JS_BLOCK_COMMENT_END)
            continue
        if source.startswith(command, index):
            return index
        index += 1
    return None


def _read_js_identifier(source: str, start: int) -> tuple[str, int] | None:
    """Read one JavaScript identifier used as a static variable reference."""
    if start >= len(source) or not (source[start].isalpha() or source[start] in {"$", _UNDERSCORE}):
        return None
    index = start + 1
    while index < len(source) and (source[index].isalnum() or source[index] in {"$", _UNDERSCORE}):
        index += 1
    return source[start:index], index


def _is_js_identifier_boundary(source: str, index: int) -> bool:
    """Return whether an offset is outside an identifier token."""
    return index < 0 or index >= len(source) or not (source[index].isalnum() or source[index] in {"$", _UNDERSCORE})


def _extract_static_string_bindings(source: str) -> dict[str, str]:
    """Resolve simple ``const name = 'value'`` bindings from custom-exec source."""
    bindings: dict[str, str] = {}
    index = 0
    declaration_tokens = ("const", "let")
    while index < len(source):
        if source[index] in _JS_QUOTE_CHARS:
            parsed_string = _read_js_quoted_string(source, index)
            if parsed_string is None:
                return bindings
            _value, index = parsed_string
            continue
        if source.startswith(_JS_LINE_COMMENT, index):
            line_end = source.find(_NEWLINE, index + len(_JS_LINE_COMMENT))
            index = len(source) if line_end < 0 else line_end + 1
            continue
        if source.startswith(_JS_BLOCK_COMMENT_START, index):
            comment_end = source.find(_JS_BLOCK_COMMENT_END, index + len(_JS_BLOCK_COMMENT_START))
            if comment_end < 0:
                return bindings
            index = comment_end + len(_JS_BLOCK_COMMENT_END)
            continue
        declaration = next(
            (
                token
                for token in declaration_tokens
                if source.startswith(token, index)
                and _is_js_identifier_boundary(source, index - 1)
                and _is_js_identifier_boundary(source, index + len(token))
            ),
            None,
        )
        if declaration is None:
            index += 1
            continue
        identifier_start = _skip_js_whitespace(source, index + len(declaration))
        parsed_identifier = _read_js_identifier(source, identifier_start)
        if parsed_identifier is None:
            index += len(declaration)
            continue
        name, after_identifier = parsed_identifier
        value_start = _skip_js_whitespace(source, after_identifier)
        if value_start >= len(source) or source[value_start] != _JS_EQUALS:
            index = after_identifier
            continue
        parsed_value = _read_js_quoted_string(source, _skip_js_whitespace(source, value_start + 1))
        if parsed_value is None:
            index = value_start + 1
            continue
        value, index = parsed_value
        bindings[name] = value
    return bindings


def _extract_nested_custom_exec_calls(source: str) -> list[tuple[_NestedCustomExecToolName, str]]:
    """Extract ordered, statically resolvable calls nested in Codex's exec transport."""
    calls: list[tuple[_NestedCustomExecToolName, str]] = []
    bindings = _extract_static_string_bindings(source)
    search_start = 0
    while True:
        exec_start = _find_next_tool_invocation(source, search_start, _CUSTOM_EXEC_COMMAND)
        patch_start = _find_next_tool_invocation(source, search_start, _CUSTOM_APPLY_PATCH_COMMAND)
        candidates = [start for start in (exec_start, patch_start) if start is not None]
        if not candidates:
            return calls
        invocation_start = min(candidates)
        command_name = _CUSTOM_EXEC_COMMAND if invocation_start == exec_start else _CUSTOM_APPLY_PATCH_COMMAND
        argument_start = _skip_js_whitespace(source, invocation_start + len(command_name))
        if argument_start >= len(source) or source[argument_start] != _JS_OPEN_PAREN:
            search_start = invocation_start + len(command_name)
            continue
        value_start = _skip_js_whitespace(source, argument_start + 1)
        if command_name == _CUSTOM_EXEC_COMMAND:
            object_end = _find_js_object_end(source, value_start)
            if object_end is None:
                search_start = argument_start + 1
                continue
            command = _extract_cmd_from_exec_object(source[value_start:object_end])
            if command is not None:
                calls.append((_EXEC_COMMAND_TOOL_NAME, command))
            search_start = object_end
            continue
        parsed_patch = _read_js_quoted_string(source, value_start)
        if parsed_patch is not None:
            patch_text, search_start = parsed_patch
            calls.append((_APPLY_PATCH_TOOL_NAME, patch_text))
            continue
        parsed_identifier = _read_js_identifier(source, value_start)
        if parsed_identifier is None:
            search_start = argument_start + 1
            continue
        binding_name, search_start = parsed_identifier
        patch_text = bindings.get(binding_name)
        if patch_text is not None:
            calls.append((_APPLY_PATCH_TOOL_NAME, patch_text))


def extract_nested_exec_commands(source: str) -> list[str]:
    """Extract statically resolvable commands from Codex's exec transport source."""
    return [
        value for tool_name, value in _extract_nested_custom_exec_calls(source) if tool_name == _EXEC_COMMAND_TOOL_NAME
    ]


def extract_nested_apply_patch_inputs(source: str) -> list[str]:
    """Extract statically resolvable apply-patch payloads from custom-exec source."""
    return [
        value for tool_name, value in _extract_nested_custom_exec_calls(source) if tool_name == _APPLY_PATCH_TOOL_NAME
    ]


def extract_nested_custom_exec_calls(source: str) -> list[tuple[_NestedCustomExecToolName, str]]:
    """Expose ordered nested tool calls for transcript consumers."""
    return _extract_nested_custom_exec_calls(source)


def extract_cell_id(output_text: str) -> str | None:
    """Read the cell identifier from the custom-exec asynchronous launch result."""
    marker_start = output_text.find(_CELL_ID_OUTPUT_PREFIX)
    if marker_start < 0:
        return None
    index = marker_start + len(_CELL_ID_OUTPUT_PREFIX)
    digits: list[str] = []
    while index < len(output_text) and output_text[index].isdigit():
        digits.append(output_text[index])
        index += 1
    return _EMPTY_STRING.join(digits) or None


def extract_payload_text(payload: object) -> str:
    """Read a Codex output payload as text, whether inline or a content-block list.

    A completed custom-exec result arrives as a ``str``; a wait completion
    arrives as a list of ``{"type": ..., "text": ...}`` content blocks. Coercing
    either shape with a bare ``str()`` turns the block-list case into an
    unreadable Python repr, so this reads each shape on its own terms.
    """
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        parts: list[str] = []
        for block in payload:
            if isinstance(block, Mapping):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return _EMPTY_STRING.join(parts)
    return str(payload)
