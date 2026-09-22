"""Explicit sealed-add declaration evidence for session-scoping."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from instrukt_ai_logging import get_logger

from teleclaude.shell_path_parser import (
    executable_command_tokens,
    extract_shell_command,
    matches_command_prefix,
    split_shell_segments,
)
from teleclaude.utils.transcript import extract_effective_tool_calls

from ._transcript_chain import TranscriptSource
from ._types import DeclarationEvidence

logger = get_logger(__name__)

_ADD_COMMAND = ("telec", "code", "add")
_COMMIT_COMMAND = ("telec", "code", "commit")
_COMMIT_APPROVED_FLAG = "--approved"
_COMMIT_ONLY_FLAG = "--only"
_SHELL_TOOLS = {"bash", "shell", "terminal", "run_shell_command", "exec_command"}


@dataclass(frozen=True)
class _AddEvent:
    """One `telec code add` invocation, in chronological order."""

    timestamp: datetime
    sequence: int
    paths: tuple[str, ...]


@dataclass(frozen=True)
class _CommitEvent:
    """One landed `telec code commit --approved` invocation.

    `only_paths` is the normalized `--only` argument set when the invocation
    carried one, or None when it did not — the two are not interchangeable:
    None means the commit's pathspec was the full live declared set (clear
    every declaration), while an empty tuple would mean an --only invocation
    with no paths, which the CLI itself refuses before it can be recorded.
    """

    timestamp: datetime
    sequence: int
    only_paths: tuple[str, ...] | None


def collect_live_declarations(
    sources: tuple[TranscriptSource, ...],
    normalize_path: Callable[[str], str],
) -> tuple[DeclarationEvidence, ...]:
    """Replay declare/commit events in order to find each path's live declaration.

    A landed commit clears only the paths it carried — its `--only` subset, or
    every live declared path when `--only` was absent — leaving every other
    declared path live past that boundary. This is a per-path replay, not a
    single global cutoff: two different commits in the same chain can each
    clear a disjoint subset without disturbing declarations neither carried.
    """
    events: list[_AddEvent | _CommitEvent] = []
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
                    # A boundary is a commit that actually landed. The bare
                    # gate-card invocation matches this prefix without
                    # creating a commit, so it must not clear anything; only
                    # an observed --approved invocation does (a failed one
                    # never reaches here — the had_error guard above already
                    # skipped it).
                    if not (record.result_observed and _COMMIT_APPROVED_FLAG in tokens):
                        logger.debug(
                            "session_scoping.declaration_boundary_not_landed",
                            timestamp=record.timestamp.isoformat(),
                            result_observed=record.result_observed,
                        )
                        continue
                    events.append(_CommitEvent(record.timestamp, sequence, _only_paths(tokens, normalize_path)))
                    sequence += 1
                    continue
                if not matches_command_prefix(segment, _ADD_COMMAND):
                    continue
                paths = tuple(filter(None, (normalize_path(token) for token in tokens[len(_ADD_COMMAND) :])))
                if paths:
                    events.append(_AddEvent(record.timestamp, sequence, paths))
                    sequence += 1

    live: dict[str, datetime] = {}
    for event in sorted(events, key=lambda item: (item.timestamp, item.sequence)):
        if isinstance(event, _AddEvent):
            for path in event.paths:
                live[path] = event.timestamp
            continue
        if event.only_paths is None:
            cleared = tuple(live)
            live.clear()
        else:
            cleared = tuple(path for path in event.only_paths if live.pop(path, None) is not None)
        logger.info(
            "session_scoping.declaration_boundary_landed",
            timestamp=event.timestamp.isoformat(),
            scope="full" if event.only_paths is None else "only",
            cleared_paths=list(cleared),
        )

    return tuple(
        sorted(
            (DeclarationEvidence(path=path, declared_at=timestamp) for path, timestamp in live.items()),
            key=lambda declaration: (declaration.declared_at, declaration.path),
        )
    )


def _only_paths(tokens: list[str], normalize_path: Callable[[str], str]) -> tuple[str, ...] | None:
    """Return a commit invocation's `--only` path arguments, or None when absent."""
    if _COMMIT_ONLY_FLAG not in tokens:
        return None
    start = tokens.index(_COMMIT_ONLY_FLAG) + 1
    raw = []
    for token in tokens[start:]:
        if token.startswith("-"):
            break
        raw.append(token)
    return tuple(filter(None, (normalize_path(token) for token in raw)))


def _canonical_tool_name(tool_name: str) -> str:
    """Normalize adapter-qualified tool names to their executable leaf."""
    normalized = tool_name.strip().lower()
    return normalized.rsplit(".", 1)[-1]
