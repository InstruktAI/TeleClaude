"""Advisory candidates for dirty paths named by successful shell activity."""

from __future__ import annotations

import re
from pathlib import Path

from teleclaude.utils.transcript import ToolCallRecord, TurnTimeline

_COMMAND_FIELDS = ("command", "cmd", "CommandLine")
_CODE_MODE_TOOL_NAMES = frozenset({"exec"})
_CODE_MODE_INPUT_FIELD = "input"
_TOOL_NAME_QUALIFIER_SEPARATOR = "."
_PATH_CHARACTER_CLASS = r"[A-Za-z0-9_./\\-]"
_PATH_BOUNDARY_TEMPLATE = r"(?<!{boundary}){path}(?!{boundary})"
_IN_PLACE_EDITOR_PATTERN = re.compile(r"(?<![\w.-])(?:sed(?:\s+\S+)*\s+-i(?:\s|\.|$)|perl\s+-pi(?:\s|\.|$))")
_FILE_VERB_PATTERN = re.compile(r"(?<![\w.-])(?:tee|touch|mkdir|mv|cp|rm|install|ln|rsync|patch)(?:\s|$)")
_GIT_MUTATION_PATTERN = re.compile(r"(?<![\w.-])git\s+(?:-C\s+\S+\s+)?(?:add|mv|rm|restore|checkout|apply)(?:\s|$)")
_REDIRECTION_PATTERN = re.compile(r"(?<!<)>>?\s*(?!/dev/null(?:\s|$))\S+")
_INTERPRETER_PATTERN = re.compile(r"(?<![\w.-])(?:python(?:\d+(?:\.\d+)*)?|node)(?=\s|$)")
_SCRIPT_MODE_PATTERN = re.compile(r"(?:\s-c(?:\s|$)|<<-?\s*['\"]?[A-Za-z_][A-Za-z0-9_]*['\"]?)")
_SCRIPT_WRITE_PATTERN = re.compile(
    r"(?:open\s*\([^)]*,\s*['\"][wax+]|write_text\s*\(|write_bytes\s*\(|"
    r"writeFile(?:Sync)?\s*\(|appendFile(?:Sync)?\s*\()"
)


def undeclared_shell_write_candidates(
    timeline: TurnTimeline,
    *,
    dirty_paths: frozenset[str],
    declared_paths: frozenset[str],
    certain_tools: frozenset[str],
    checkout_root: Path,
) -> tuple[str, ...]:
    """Return dirty undeclared paths named in successful file-writing shell commands."""
    unresolved = dirty_paths - declared_paths
    candidates: set[str] = set()
    for record in timeline.tool_calls:
        if record.had_error or not record.result_observed:
            continue
        if _canonical_tool_name(record.tool_name) in certain_tools:
            continue
        commands = _command_texts(record)
        if not any(_is_file_write_command(command) for command in commands):
            continue
        for path in unresolved:
            if _command_names_path(commands, path, checkout_root):
                candidates.add(path)
    return tuple(sorted(candidates))


def _canonical_tool_name(tool_name: str) -> str:
    """Normalize the timeline's provider-qualified tool name."""
    normalized = tool_name.strip().lower()
    return (
        normalized.rsplit(_TOOL_NAME_QUALIFIER_SEPARATOR, 1)[-1]
        if _TOOL_NAME_QUALIFIER_SEPARATOR in normalized
        else normalized
    )


def _command_texts(record: ToolCallRecord) -> tuple[str, ...]:
    """Read only the recorded command fields owned by the recognized runtimes."""
    commands: list[str] = []
    for field in _COMMAND_FIELDS:
        value = record.input_data.get(field)
        if isinstance(value, str) and value:
            commands.append(value)
    if _canonical_tool_name(record.tool_name) in _CODE_MODE_TOOL_NAMES:
        value = record.input_data.get(_CODE_MODE_INPUT_FIELD)
        if isinstance(value, str) and value:
            commands.append(value)
    return tuple(commands)


def _is_file_write_command(command: str) -> bool:
    """Recognize the closed shell syntax set that can write files."""
    if any(
        pattern.search(command)
        for pattern in (_IN_PLACE_EDITOR_PATTERN, _FILE_VERB_PATTERN, _GIT_MUTATION_PATTERN, _REDIRECTION_PATTERN)
    ):
        return True
    return bool(
        _INTERPRETER_PATTERN.search(command)
        and _SCRIPT_MODE_PATTERN.search(command)
        and _SCRIPT_WRITE_PATTERN.search(command)
    )


def _command_names_path(commands: tuple[str, ...], path: str, checkout_root: Path) -> bool:
    """Match a known dirty path literally in its repo-relative or absolute form."""
    absolute_path = (checkout_root / path).as_posix()
    for candidate in (path, absolute_path):
        matcher = re.compile(_PATH_BOUNDARY_TEMPLATE.format(boundary=_PATH_CHARACTER_CLASS, path=re.escape(candidate)))
        if any(matcher.search(command) for command in commands):
            return True
    return False
