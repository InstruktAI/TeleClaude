"""Structured extraction for Codex custom-exec transport envelopes."""

from __future__ import annotations

import json
from collections.abc import Mapping

_CUSTOM_EXEC_NAME = "exec"
_CUSTOM_EXEC_COMMAND = "tools.exec_command"
_EXEC_COMMAND_TOOL_NAME = "exec_command"
_WAIT_TOOL_NAME = "wait"
_CMD_PROPERTY_NAME = "cmd"
_CELL_ID_PROPERTY_NAME = "cell_id"
_CELL_ID_OUTPUT_PREFIX = "Script running with cell ID "
_PROCESS_EXIT_CODE_PREFIX = "Process exited with code "
_JS_OPEN_PAREN = "("
_JS_CLOSE_PAREN = ")"
_JS_OPEN_BRACE = "{"
_JS_CLOSE_BRACE = "}"
_JS_OPEN_BRACKET = "["
_JS_CLOSE_BRACKET = "]"
_JS_COMMA = ","
_JS_COLON = ":"
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
_EXIT_CODE_FIELD = "exit_code"
_CALL_ID_FIELD = "call_id"
_INPUT_FIELD = "input"
_NAME_FIELD = "name"
_OUTPUT_FIELD = "output"
_UNKNOWN_TOOL_NAME = "unknown"


def extract_process_exit_code(output_text: str) -> int | None:
    """Read the harness's textual child-process completion status when present."""
    marker_start = output_text.find(_PROCESS_EXIT_CODE_PREFIX)
    if marker_start < 0:
        return None
    remainder = output_text[marker_start + len(_PROCESS_EXIT_CODE_PREFIX) :].strip()
    digits: list[str] = []
    for character in remainder:
        if not character.isdigit():
            break
        digits.append(character)
    return int(_EMPTY_STRING.join(digits)) if digits else None


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


def _find_next_exec_invocation(source: str, start: int) -> int | None:
    """Find an exec-command call in JavaScript code, excluding strings and comments."""
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
        if source.startswith(_CUSTOM_EXEC_COMMAND, index):
            return index
        index += 1
    return None


def extract_nested_exec_commands(source: str) -> list[str]:
    """Extract statically resolvable commands from Codex's exec transport source."""
    commands: list[str] = []
    search_start = 0
    while True:
        invocation_start = _find_next_exec_invocation(source, search_start)
        if invocation_start is None:
            return commands
        argument_start = _skip_js_whitespace(source, invocation_start + len(_CUSTOM_EXEC_COMMAND))
        if argument_start >= len(source) or source[argument_start] != _JS_OPEN_PAREN:
            search_start = invocation_start + len(_CUSTOM_EXEC_COMMAND)
            continue
        object_start = _skip_js_whitespace(source, argument_start + 1)
        object_end = _find_js_object_end(source, object_start)
        if object_end is None:
            search_start = argument_start + 1
            continue
        command = _extract_cmd_from_exec_object(source[object_start:object_end])
        if command is not None:
            commands.append(command)
        search_start = object_end


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


def _extract_structured_exit_codes(payload: object) -> list[int]:
    """Return observed structured child exit codes in their serialized order."""
    if isinstance(payload, Mapping):
        exit_code = payload.get(_EXIT_CODE_FIELD)
        if isinstance(exit_code, int) and not isinstance(exit_code, bool):
            return [exit_code]
        return [code for value in payload.values() for code in _extract_structured_exit_codes(value)]
    if isinstance(payload, list):
        return [code for value in payload for code in _extract_structured_exit_codes(value)]
    return []


def custom_record_successes(output_text: str, record_count: int) -> list[bool]:
    """Map an observed child status to every unwrapped command without guessing."""
    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError:
        payload = None
    exit_codes = _extract_structured_exit_codes(payload)
    if len(exit_codes) == record_count:
        return [exit_code == 0 for exit_code in exit_codes]
    process_exit_code = extract_process_exit_code(output_text)
    if record_count == 1 and process_exit_code is not None:
        return [process_exit_code == 0]
    return [False] * record_count
