"""Explicit sealed-add declaration evidence for session-scoping."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from teleclaude.shell_path_parser import (
    executable_command_tokens,
    extract_shell_command,
    matches_command_prefix,
    split_shell_segments,
)
from teleclaude.utils.transcript import extract_effective_tool_calls

from ._transcript_chain import TranscriptSource
from ._types import DeclarationEvidence

_ADD_COMMAND = ("telec", "code", "add")
_COMMIT_COMMAND = ("telec", "code", "commit")
_SHELL_TOOLS = {"bash", "shell", "terminal", "run_shell_command", "exec_command"}


def collect_live_declarations(
    sources: tuple[TranscriptSource, ...],
    normalize_path: Callable[[str], str],
) -> tuple[DeclarationEvidence, ...]:
    """Read declarations after the latest successful commit across one chain."""
    records: list[tuple[datetime, int, tuple[str, ...], bool]] = []
    sequence = 0
    for source in sources:
        timeline = extract_effective_tool_calls(
            source.path,
            source.agent,
            native_session_id=source.native_session_id,
            scope="session",
        )
        if not timeline.has_data:
            raise ValueError(f"Session transcript has no readable records: {source.path}")
        for record in timeline.tool_calls:
            if record.timestamp is None or record.timestamp.tzinfo is None or record.had_error:
                continue
            if _canonical_tool_name(record.tool_name) not in _SHELL_TOOLS:
                continue
            command = extract_shell_command(record.input_data)
            for segment in split_shell_segments(command):
                tokens = executable_command_tokens(segment)
                if matches_command_prefix(segment, _COMMIT_COMMAND):
                    records.append((record.timestamp, sequence, (), True))
                    sequence += 1
                    continue
                if not matches_command_prefix(segment, _ADD_COMMAND):
                    continue
                paths = tuple(filter(None, (normalize_path(token) for token in tokens[len(_ADD_COMMAND) :])))
                if paths:
                    records.append((record.timestamp, sequence, paths, False))
                    sequence += 1

    latest_commit = max((timestamp for timestamp, _sequence, _paths, is_commit in records if is_commit), default=None)
    declarations = {
        DeclarationEvidence(path=path, declared_at=timestamp)
        for timestamp, _sequence, paths, is_commit in records
        if not is_commit and (latest_commit is None or timestamp > latest_commit)
        for path in paths
    }
    return tuple(sorted(declarations, key=lambda declaration: (declaration.declared_at, declaration.path)))


def _canonical_tool_name(tool_name: str) -> str:
    """Normalize adapter-qualified tool names to their executable leaf."""
    normalized = tool_name.strip().lower()
    return normalized.rsplit(".", 1)[-1]
