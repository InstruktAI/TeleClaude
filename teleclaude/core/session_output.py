"""Agent-runtime turn-output contracts."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

NOOP_SENTINEL = "NOOP"
_CONTENT_KEY = "content"
_TEXT_KEY = "text"
_TYPE_KEY = "type"


class StopOutputKind(StrEnum):
    """Observed result of extracting the response for one agent stop."""

    SUBSTANTIVE = "substantive"
    EMPTY = "empty"
    SUPPRESSED_NOOP = "suppressed_noop"
    UNAVAILABLE = "unavailable"


class StopOutputDisposition(StrEnum):
    """The atomic persistence action chosen by agent-runtime."""

    PRESERVE = "preserve"
    REPLACE = "replace"


@dataclass(frozen=True)
class StopOutputResult:
    """Typed stop extraction result; storage never infers it from text."""

    kind: StopOutputKind
    raw_output: str | None = None
    response_entry_id: str | None = None

    @property
    def disposition(self) -> StopOutputDisposition:
        """Return the explicit persistence choice for this observed result."""
        if self.kind in {StopOutputKind.SUPPRESSED_NOOP, StopOutputKind.UNAVAILABLE}:
            return StopOutputDisposition.PRESERVE
        return StopOutputDisposition.REPLACE

    @property
    def is_suppressed(self) -> bool:
        """Return whether this turn is a structural no-output completion."""
        return self.kind is StopOutputKind.SUPPRESSED_NOOP

    @property
    def has_substantive_output(self) -> bool:
        """Return whether this stop replaces retained output with a payload."""
        return self.kind is StopOutputKind.SUBSTANTIVE


def classify_stop_output(text: str) -> StopOutputResult:
    """Classify one normalized, corresponding agent response."""
    if not text.strip():
        return StopOutputResult(StopOutputKind.EMPTY)
    if is_bare_noop_output(text):
        return StopOutputResult(StopOutputKind.SUPPRESSED_NOOP)
    return StopOutputResult(StopOutputKind.SUBSTANTIVE, raw_output=text)


class _AssistantOutputPartType(StrEnum):
    """Transcript part types relevant to authored assistant output."""

    TEXT = "text"
    INPUT_TEXT = "input_text"
    OUTPUT_TEXT = "output_text"
    THINKING = "thinking"


_TEXT_PART_TYPES = frozenset(
    {
        _AssistantOutputPartType.TEXT,
        _AssistantOutputPartType.INPUT_TEXT,
        _AssistantOutputPartType.OUTPUT_TEXT,
    }
)


def is_bare_noop_output(text: str) -> bool:
    """Return whether text is solely the no-output sentinel."""
    return text.strip() == NOOP_SENTINEL


def assistant_output_parts_are_bare_noop(parts: Iterable[tuple[str, str | None]]) -> bool:
    """Return whether visible authored text is solely the sentinel and the turn is tool-free."""
    sentinel_seen = False
    for part_type, text in parts:
        if part_type == _AssistantOutputPartType.THINKING:
            continue
        if part_type not in _TEXT_PART_TYPES or text is None:
            return False
        if not text.strip():
            continue
        if not is_bare_noop_output(text):
            return False
        sentinel_seen = True
    return sentinel_seen


def assistant_messages_are_bare_noop(messages: Iterable[Mapping[str, object]]) -> bool:
    """Reduce normalized assistant transcript messages to the authored-output contract."""
    parts: list[tuple[str, str | None]] = []
    for message in messages:
        content = message.get(_CONTENT_KEY)
        if isinstance(content, str):
            parts.append((_AssistantOutputPartType.TEXT.value, content))
            continue
        if not isinstance(content, list):
            return False
        for block in content:
            if not isinstance(block, Mapping):
                return False
            part_type = block.get(_TYPE_KEY)
            if not isinstance(part_type, str):
                return False
            text = block.get(_TEXT_KEY)
            parts.append((part_type, text if isinstance(text, str) else None))
    return assistant_output_parts_are_bare_noop(parts)
