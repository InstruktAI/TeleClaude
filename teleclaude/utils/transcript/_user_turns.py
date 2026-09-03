"""Real user-turn detection for agent-native transcript entries."""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from teleclaude.core.agents import AgentName
from teleclaude.core.injected_text import TranscriptEntryKind, cut_transcript_entry
from teleclaude.core.models import JsonDict

from ._parsers import normalize_transcript_entry_message
from ._utils import _parse_timestamp


class CodexContentItemKind(StrEnum):
    """Current upstream content kinds that positively identify human input."""

    USER_TEXT = "user.text"
    USER_IMAGE = "user.image"
    USER_AUDIO = "user.audio"


_CLAUDE_TASK_NOTIFICATION_RE = re.compile(r"^\s*<task-notification\b", re.DOTALL)
_CLAUDE_TEXT_ARTIFACT_RE = re.compile(
    r"^\s*<(?:system-reminder|task-notification|teammate-message)\b[^>]*>.*</(?:system-reminder|task-notification|teammate-message)\s*>\s*$",
    re.DOTALL,
)
_DEEPSEEK_TEXT_ARTIFACT_RE = re.compile(r"^\s*<system-reminder\b[^>]*>.*</system-reminder\s*>\s*$", re.DOTALL)
_RUNTIME_CONTEXT_PREFIXES = ("Current runtime context.", "This is an automatically generated checkpoint")
_CLAUDE_HOOK_PREFIXES = ("Stop hook feedback:", "PreToolUse hook feedback:")
_NON_CODEX_RUNTIME_SPANS = (
    re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL),
    re.compile(r"<hook_context>.*?</hook_context>", re.DOTALL),
    re.compile(r"<command-message>.*?</command-message>", re.DOTALL),
    re.compile(r"<command-name>.*?</command-name>", re.DOTALL),
    re.compile(r"<command-args>.*?</command-args>", re.DOTALL),
)
_NON_CODEX_COMPATIBILITY_SPANS = (
    re.compile(r"<environment_context>.*?</environment_context>", re.DOTALL),
    re.compile(
        r"<codex_internal_context\b(?=[^>]*\ssource\s*=\s*[\"']goal[\"'])[^>]*>.*?</codex_internal_context\s*>",
        re.DOTALL,
    ),
    re.compile(r"<INSTRUCTIONS>.*?</INSTRUCTIONS>", re.DOTALL),
    re.compile(r"^# AGENTS\.md instructions for .*$", re.MULTILINE),
)
_SERIALIZED_CONTENT_RE = re.compile(r"^\s*\[\s*\{.*['\"]text['\"]\s*:", re.DOTALL)
_CLAUDE_COMPACT_SUMMARY_FIELD = "isCompactSummary"
_CLAUDE_ENTRY_ID_FIELD = "uuid"
_CLAUDE_PARENT_ENTRY_ID_FIELD = "parentUuid"
_MESSAGE_ROLE_FIELD = "role"
_ASSISTANT_ROLE = "assistant"
_USER_ROLE = "user"
_TEXT_BLOCK_TYPE = "text"
_CODEX_HUMAN_CONTENT_KINDS = frozenset(CodexContentItemKind)
_CODEX_CONTENT_KINDS_FIELD = "content_item_kinds"
_CODEX_METADATA_FIELD = "internal_chat_message_metadata_passthrough"
_CODEX_TEXT_BLOCK_TYPES = frozenset({"input_text", "text"})
_CODEX_LEGACY_TAGS = {
    "environment_context": "environment_context",
    "skill": "skill",
    "user_shell_command": "user_shell_command",
    "turn_aborted": "turn_aborted",
    "subagent_notification": "subagent_notification",
    "recommended_plugins": "recommended_plugins",
    "goal_context": "goal_context",
}
_CODEX_TAG_PATTERN = re.compile(
    r"<(?P<tag>environment_context|skill|user_shell_command|turn_aborted|subagent_notification|recommended_plugins|goal_context)\b[^>]*>.*?</(?P=tag)\s*>",
    re.DOTALL,
)
_CODEX_INTERNAL_CONTEXT_PATTERN = re.compile(
    r"<codex_internal_context\b(?=[^>]*\bsource\s*=\s*[\"'](?P<source>[a-z][a-z0-9_-]*)[\"'])[^>]*>.*?</codex_internal_context\s*>",
    re.DOTALL,
)
_CODEX_EXTERNAL_CONTEXT_PATTERN = re.compile(
    r"<(?P<tag>external_[a-z][a-z0-9_]*)\b[^>]*>.*?</(?P=tag)\s*>",
    re.DOTALL,
)
_CODEX_HOOK_PROMPT_PATTERN = re.compile(r"<hook_prompt\b[^>]*>.*?</hook_prompt\s*>", re.DOTALL)
_CODEX_HOOK_RUN_ID_ATTRIBUTE_RE = re.compile(r"\bhook_run_id\s*=\s*[\"'][^\"']+")
_CODEX_AGENTS_INSTRUCTIONS_PATTERN = re.compile(
    r"(?m)^# AGENTS\.md instructions(?: for .*)?[ \t]*(?:\r?\n.*?<INSTRUCTIONS>.*?</INSTRUCTIONS\s*>)?",
    re.DOTALL,
)


class ClaudeTurnCommitmentOutcome(StrEnum):
    """Closed receipt-less Claude candidate commitment outcomes."""

    COMMITTED = "committed"
    PROVISIONAL = "provisional"
    UNRESOLVED = "unresolved"


class ClaudeTurnCommitmentReason(StrEnum):
    """Stable structural reasons for a Claude candidate commitment outcome."""

    ASSISTANT_DESCENDANT = "assistant_descendant"
    ASSISTANT_DESCENDANT_PENDING = "assistant_descendant_pending"
    CANDIDATE_NOT_FOUND = "candidate_not_found"
    CANDIDATE_NOT_USER = "candidate_not_user"
    DUPLICATE_ENTRY_ID = "duplicate_entry_id"
    MALFORMED_DESCENDANT_ID = "malformed_descendant_id"
    MISSING_PARENT_ENTRY = "missing_parent_entry"
    ANCESTRY_CYCLE = "ancestry_cycle"


class UserContentOrigin(StrEnum):
    """Native provenance for one user-role content position."""

    CANDIDATE_HUMAN = "candidate_human"
    RUNTIME = "runtime"


class CodexLegacyShape(StrEnum):
    """Registered upstream-grounded Codex compatibility shapes."""

    AGENTS_INSTRUCTIONS = "agents_instructions"
    ENVIRONMENT_CONTEXT = "environment_context"
    SKILL = "skill"
    USER_SHELL_COMMAND = "user_shell_command"
    TURN_ABORTED = "turn_aborted"
    SUBAGENT_NOTIFICATION = "subagent_notification"
    RECOMMENDED_PLUGINS = "recommended_plugins"
    GOAL_CONTEXT = "goal_context"
    INTERNAL_CONTEXT = "internal_context"
    EXTERNAL_CONTEXT = "external_context"
    HOOK_PROMPT = "hook_prompt"


@dataclass(frozen=True)
class CodexStructuralSpan:
    """One registered Codex runtime fragment inside a text value."""

    shape: CodexLegacyShape
    start: int
    end: int
    source: str | None = None


@dataclass(frozen=True)
class CodexStructuralRecognition:
    """Structural recognition shared by fallback, ingress, and normalization."""

    spans: tuple[CodexStructuralSpan, ...]
    is_complete: bool

    def has_shape(self, shape: CodexLegacyShape) -> bool:
        """Return whether this text contains a registered shape."""
        return any(span.shape is shape for span in self.spans)


@dataclass(frozen=True)
class UserContentBlockClassification:
    """Immutable provenance decision for one native user content block."""

    index: int
    block_type: str | None
    text: str | None
    origin: UserContentOrigin
    raw_kind: str | None
    structural_recognition: CodexStructuralRecognition | None


@dataclass(frozen=True)
class ClaudeTurnCommitment:
    """Structural commitment decision for one receipt-less Claude candidate."""

    outcome: ClaudeTurnCommitmentOutcome
    reason: ClaudeTurnCommitmentReason
    candidate_entry_id: str
    parent_entry_id: str | None
    alternative_entry_ids: tuple[str, ...]


@dataclass(frozen=True)
class _ClaudeGraphNode:
    """Indexed Claude entry fields needed for descendant traversal."""

    entry_id: str | None
    parent_entry_id: str | None
    role: str | None
    is_real_user: bool


@dataclass(frozen=True)
class RealUserTurn:
    """The transcript location and content for a real user turn."""

    entry_index: int
    next_index: int
    text: str | None
    timestamp: datetime | None


class ClaudeTurnCommitmentResolver:
    """One-pass Claude graph index with per-candidate commitment queries."""

    def __init__(self, entries: Sequence[JsonDict]) -> None:
        self._nodes_by_id: dict[str, _ClaudeGraphNode] = {}
        self._duplicate_entry_ids: set[str] = set()
        self._children_by_parent_id: dict[str, list[_ClaudeGraphNode]] = {}
        for entry in entries:
            raw_entry_id = entry.get(_CLAUDE_ENTRY_ID_FIELD)
            entry_id = raw_entry_id if isinstance(raw_entry_id, str) and raw_entry_id else None
            raw_parent_entry_id = entry.get(_CLAUDE_PARENT_ENTRY_ID_FIELD)
            parent_entry_id = (
                raw_parent_entry_id if isinstance(raw_parent_entry_id, str) and raw_parent_entry_id else None
            )
            message = normalize_transcript_entry_message(entry)
            raw_role = message.get(_MESSAGE_ROLE_FIELD) if isinstance(message, Mapping) else None
            role = raw_role if isinstance(raw_role, str) else None
            node = _ClaudeGraphNode(
                entry_id=entry_id,
                parent_entry_id=parent_entry_id,
                role=role,
                is_real_user=is_real_user_turn_entry(entry, AgentName.CLAUDE),
            )
            if entry_id is not None:
                if entry_id in self._nodes_by_id:
                    self._duplicate_entry_ids.add(entry_id)
                else:
                    self._nodes_by_id[entry_id] = node
            if parent_entry_id is not None:
                self._children_by_parent_id.setdefault(parent_entry_id, []).append(node)

    def resolve(self, candidate_entry_id: str) -> ClaudeTurnCommitment:
        """Resolve whether Claude continued from one receipt-less candidate."""
        candidate = self._nodes_by_id.get(candidate_entry_id)
        if candidate is None:
            return ClaudeTurnCommitment(
                outcome=ClaudeTurnCommitmentOutcome.UNRESOLVED,
                reason=ClaudeTurnCommitmentReason.CANDIDATE_NOT_FOUND,
                candidate_entry_id=candidate_entry_id,
                parent_entry_id=None,
                alternative_entry_ids=(),
            )

        parent_entry_id = candidate.parent_entry_id
        sibling_nodes = self._children_by_parent_id.get(parent_entry_id, ()) if parent_entry_id is not None else ()
        alternatives = tuple(
            node.entry_id
            for node in sibling_nodes
            if node.entry_id is not None and node.entry_id != candidate_entry_id and node.is_real_user
        )

        def result(
            outcome: ClaudeTurnCommitmentOutcome,
            reason: ClaudeTurnCommitmentReason,
        ) -> ClaudeTurnCommitment:
            return ClaudeTurnCommitment(
                outcome=outcome,
                reason=reason,
                candidate_entry_id=candidate_entry_id,
                parent_entry_id=parent_entry_id,
                alternative_entry_ids=alternatives,
            )

        if candidate_entry_id in self._duplicate_entry_ids:
            return result(ClaudeTurnCommitmentOutcome.UNRESOLVED, ClaudeTurnCommitmentReason.DUPLICATE_ENTRY_ID)
        if not candidate.is_real_user:
            return result(ClaudeTurnCommitmentOutcome.UNRESOLVED, ClaudeTurnCommitmentReason.CANDIDATE_NOT_USER)
        if parent_entry_id is not None and parent_entry_id not in self._nodes_by_id:
            return result(ClaudeTurnCommitmentOutcome.UNRESOLVED, ClaudeTurnCommitmentReason.MISSING_PARENT_ENTRY)

        pending_ids = [candidate_entry_id]
        visited_ids: set[str] = set()
        assistant_descendant_present = False
        while pending_ids:
            parent_id = pending_ids.pop()
            if parent_id in visited_ids:
                return result(ClaudeTurnCommitmentOutcome.UNRESOLVED, ClaudeTurnCommitmentReason.ANCESTRY_CYCLE)
            visited_ids.add(parent_id)
            for child in self._children_by_parent_id.get(parent_id, ()):
                child_id = child.entry_id
                if child_id is None:
                    return result(
                        ClaudeTurnCommitmentOutcome.UNRESOLVED,
                        ClaudeTurnCommitmentReason.MALFORMED_DESCENDANT_ID,
                    )
                if child_id in self._duplicate_entry_ids:
                    return result(
                        ClaudeTurnCommitmentOutcome.UNRESOLVED,
                        ClaudeTurnCommitmentReason.DUPLICATE_ENTRY_ID,
                    )
                if child.role == _ASSISTANT_ROLE:
                    assistant_descendant_present = True
                pending_ids.append(child_id)

        if assistant_descendant_present:
            return result(ClaudeTurnCommitmentOutcome.COMMITTED, ClaudeTurnCommitmentReason.ASSISTANT_DESCENDANT)
        return result(
            ClaudeTurnCommitmentOutcome.PROVISIONAL,
            ClaudeTurnCommitmentReason.ASSISTANT_DESCENDANT_PENDING,
        )


def resolve_claude_turn_commitment(
    entries: Sequence[JsonDict],
    candidate_entry_id: str,
) -> ClaudeTurnCommitment:
    """Resolve one candidate through a freshly indexed Claude transcript graph."""
    return ClaudeTurnCommitmentResolver(entries).resolve(candidate_entry_id)


def _agent_value(agent_name: AgentName | str | None) -> str | None:
    if isinstance(agent_name, AgentName):
        return agent_name.value
    if isinstance(agent_name, str):
        return agent_name.lower()
    return None


def _is_platform_control_text(text: str) -> bool:
    """Recognize only one complete registered platform-control envelope."""
    segments = cut_transcript_entry(text, is_user_entry=True)
    return len(segments) == 1 and segments[0].kind is TranscriptEntryKind.PLATFORM_CONTROL


def _codex_structural_recognition(text: str) -> CodexStructuralRecognition:
    """Recognize registered Codex fragments without interpreting their bodies."""
    spans: list[CodexStructuralSpan] = []

    for match in _CODEX_TAG_PATTERN.finditer(text):
        shape = CodexLegacyShape(_CODEX_LEGACY_TAGS[match.group("tag")])
        spans.append(CodexStructuralSpan(shape=shape, start=match.start(), end=match.end()))
    for match in _CODEX_INTERNAL_CONTEXT_PATTERN.finditer(text):
        spans.append(
            CodexStructuralSpan(
                shape=CodexLegacyShape.INTERNAL_CONTEXT,
                start=match.start(),
                end=match.end(),
                source=match.group("source"),
            )
        )
    for match in _CODEX_EXTERNAL_CONTEXT_PATTERN.finditer(text):
        spans.append(CodexStructuralSpan(shape=CodexLegacyShape.EXTERNAL_CONTEXT, start=match.start(), end=match.end()))
    for match in _CODEX_HOOK_PROMPT_PATTERN.finditer(text):
        spans.append(CodexStructuralSpan(shape=CodexLegacyShape.HOOK_PROMPT, start=match.start(), end=match.end()))
    for match in _CODEX_AGENTS_INSTRUCTIONS_PATTERN.finditer(text):
        spans.append(
            CodexStructuralSpan(shape=CodexLegacyShape.AGENTS_INSTRUCTIONS, start=match.start(), end=match.end())
        )

    ordered = tuple(sorted(spans, key=lambda span: (span.start, span.end)))
    cursor = 0
    is_complete = bool(ordered)
    for span in ordered:
        if span.start < cursor or text[cursor : span.start].strip():
            is_complete = False
            break
        cursor = span.end
    if is_complete and text[cursor:].strip():
        is_complete = False
    return CodexStructuralRecognition(spans=ordered, is_complete=is_complete)


def _codex_legacy_recognition_is_valid(text: str, recognition: CodexStructuralRecognition) -> bool:
    """Apply the upstream fallback's hook-prompt validity requirement."""
    if not recognition.is_complete:
        return False
    for span in recognition.spans:
        if span.shape is CodexLegacyShape.HOOK_PROMPT:
            fragment = text[span.start : span.end]
            if not _CODEX_HOOK_RUN_ID_ATTRIBUTE_RE.search(fragment):
                return False
    return True


def _is_codex_hook_ingress_artifact(recognition: CodexStructuralRecognition) -> bool:
    """Preserve the narrower text-only hook-ingress artifact contract."""
    if recognition.has_shape(CodexLegacyShape.AGENTS_INSTRUCTIONS):
        return True
    if not recognition.is_complete:
        return False
    return any(
        span.shape in {CodexLegacyShape.ENVIRONMENT_CONTEXT, CodexLegacyShape.HOOK_PROMPT}
        or (span.shape is CodexLegacyShape.INTERNAL_CONTEXT and span.source == "goal")
        for span in recognition.spans
    )


def _codex_content_kinds(message: Mapping[str, object], content: list[object]) -> tuple[str, ...] | None:
    """Return only complete, string-aligned Codex metadata."""
    metadata = message.get(_CODEX_METADATA_FIELD)
    if not isinstance(metadata, Mapping):
        return None
    kinds = metadata.get(_CODEX_CONTENT_KINDS_FIELD)
    if not isinstance(kinds, list) or len(kinds) != len(content) or not all(isinstance(kind, str) for kind in kinds):
        return None
    return tuple(kinds)


def _user_block_text(block: object) -> tuple[str | None, str | None]:
    """Extract a user text position without flattening the surrounding content."""
    if not isinstance(block, Mapping):
        return None, None
    raw_type = block.get("type")
    block_type = raw_type if isinstance(raw_type, str) else None
    if block_type not in _CODEX_TEXT_BLOCK_TYPES:
        return block_type, None
    raw_text = block.get("text")
    return block_type, raw_text if isinstance(raw_text, str) and raw_text.strip() else None


def classify_user_content_blocks(
    entry: Mapping[str, object], agent_name: AgentName | str | None
) -> tuple[UserContentBlockClassification, ...]:
    """Classify native user content before any caller flattens it into text."""
    message = normalize_transcript_entry_message(entry)
    if not isinstance(message, Mapping) or message.get(_MESSAGE_ROLE_FIELD) != _USER_ROLE:
        return ()

    content = message.get("content")
    agent = _agent_value(agent_name)
    if isinstance(content, str):
        recognition = _codex_structural_recognition(content) if agent == AgentName.CODEX.value else None
        is_runtime = _is_platform_control_text(content) or (
            recognition is not None and _codex_legacy_recognition_is_valid(content, recognition)
        )
        return (
            UserContentBlockClassification(
                index=0,
                block_type=_TEXT_BLOCK_TYPE,
                text=content if content.strip() else None,
                origin=UserContentOrigin.RUNTIME if is_runtime else UserContentOrigin.CANDIDATE_HUMAN,
                raw_kind=None,
                structural_recognition=recognition,
            ),
        )
    if not isinstance(content, list):
        return ()

    kinds = _codex_content_kinds(message, content) if agent == AgentName.CODEX.value else None
    classifications: list[UserContentBlockClassification] = []
    for index, block in enumerate(content):
        block_type, text = _user_block_text(block)
        recognition = _codex_structural_recognition(text) if agent == AgentName.CODEX.value and text else None
        raw_kind = kinds[index] if kinds is not None else None
        is_control = text is not None and _is_platform_control_text(text)
        if is_control:
            origin = UserContentOrigin.RUNTIME
        elif kinds is not None:
            origin = (
                UserContentOrigin.CANDIDATE_HUMAN
                if raw_kind in _CODEX_HUMAN_CONTENT_KINDS
                else UserContentOrigin.RUNTIME
            )
        elif recognition is not None and _codex_legacy_recognition_is_valid(text, recognition):
            origin = UserContentOrigin.RUNTIME
        else:
            origin = UserContentOrigin.CANDIDATE_HUMAN
        classifications.append(
            UserContentBlockClassification(
                index=index,
                block_type=block_type,
                text=text,
                origin=origin,
                raw_kind=raw_kind,
                structural_recognition=recognition,
            )
        )
    return tuple(classifications)


def _candidate_human_texts(entry: Mapping[str, object], agent_name: AgentName | str | None) -> tuple[str, ...]:
    """Return ordered text whose native provenance permits human projection."""
    return tuple(
        classification.text
        for classification in classify_user_content_blocks(entry, agent_name)
        if classification.origin is UserContentOrigin.CANDIDATE_HUMAN and classification.text is not None
    )


def is_runtime_artifact_text(agent_name: AgentName | str | None, text: str) -> bool:
    """Recognize complete runtime-owned prompt text without generic XML guessing."""
    if _is_platform_control_text(text):
        return True
    agent = _agent_value(agent_name)
    stripped = text.lstrip()
    if agent == AgentName.CLAUDE.value:
        return bool(_CLAUDE_TEXT_ARTIFACT_RE.fullmatch(text) or stripped.startswith(_CLAUDE_HOOK_PREFIXES))
    if agent == AgentName.CODEX.value:
        return _is_codex_hook_ingress_artifact(_codex_structural_recognition(text))
    if agent == AgentName.DEEPSEEK.value:
        return bool(_DEEPSEEK_TEXT_ARTIFACT_RE.fullmatch(text) or stripped.startswith(_RUNTIME_CONTEXT_PREFIXES))
    return False


def is_runtime_artifact_entry(entry: Mapping[str, object], agent_name: AgentName | str | None) -> bool:
    """Recognize native structured runtime artifacts for one declared runtime."""
    message = normalize_transcript_entry_message(entry)
    text = extract_text_from_message_content(message.get("content"), "user") if isinstance(message, Mapping) else None
    agent = _agent_value(agent_name)
    if agent == AgentName.CLAUDE.value:
        return _is_claude_internal_user_entry(entry, text)
    if text is None:
        return False
    if agent == AgentName.CODEX.value:
        classifications = classify_user_content_blocks(entry, agent_name)
        textual = tuple(classification for classification in classifications if classification.text is not None)
        return bool(textual) and all(classification.origin is UserContentOrigin.RUNTIME for classification in textual)
    if agent == AgentName.GEMINI.value:
        return _is_gemini_internal_user_entry(text)
    if agent == AgentName.DEEPSEEK.value:
        return _is_deepseek_internal_user_entry(text) or is_runtime_artifact_text(agent, text)
    return is_runtime_artifact_text(agent, text)


def normalize_runtime_user_text(agent_name: AgentName | str | None, text: str) -> str:
    """Remove registered runtime spans without re-deciding native provenance."""
    normalized = text
    if _SERIALIZED_CONTENT_RE.match(text):
        try:
            parsed = ast.literal_eval(text)
        except (ValueError, SyntaxError):
            parsed = None
        if isinstance(parsed, list):
            chunks = [
                block["text"] for block in parsed if isinstance(block, dict) and isinstance(block.get("text"), str)
            ]
            if chunks:
                normalized = "\n\n".join(chunks)
    for pattern in _NON_CODEX_RUNTIME_SPANS:
        normalized = pattern.sub("", normalized)
    if _agent_value(agent_name) == AgentName.CODEX.value:
        recognition = _codex_structural_recognition(normalized)
        for span in reversed(recognition.spans):
            normalized = f"{normalized[: span.start]}{normalized[span.end :]}"
    else:
        for pattern in _NON_CODEX_COMPATIBILITY_SPANS:
            normalized = pattern.sub("", normalized)
    return normalized.strip()


def _entry_timestamp(entry: Mapping[str, object]) -> datetime | None:
    entry_ts = entry.get("timestamp")
    return _parse_timestamp(entry_ts) if isinstance(entry_ts, str) else None


def extract_text_from_message_content(content: object, role: str) -> str | None:
    """Extract the first text block from normalized message content."""
    if isinstance(content, str):
        return content if content.strip() else None

    if not isinstance(content, list):
        return None

    valid_types = ("input_text", "text") if role == "user" else ("text", "output_text")
    for block in content:
        if not isinstance(block, dict) or block.get("type") not in valid_types:
            continue
        text = str(block.get("text", ""))
        if text.strip():
            return text
    return None


def is_user_tool_result_only_message(message: Mapping[str, object]) -> bool:
    """Return True when a user message only carries tool_result blocks.

    Claude writes tool outputs as role=user messages. Those entries are part
    of the assistant turn and must not reset current-turn boundaries.
    """
    if message.get("role") != "user":
        return False

    content = message.get("content")
    if isinstance(content, str):
        return False
    if not isinstance(content, list) or not content:
        return False

    saw_block = False
    for block in content:
        if not isinstance(block, dict):
            return False
        saw_block = True
        if block.get("type") != "tool_result":
            return False
    return saw_block


def _is_teleclaude_control_text(text: str) -> bool:
    """Return True for exact TeleClaude-owned non-human input envelopes."""
    return _is_platform_control_text(text)


def _is_claude_internal_user_entry(entry: Mapping[str, object], text: str | None) -> bool:
    """Classify Claude Code user-shaped runtime artifacts by native envelope."""
    if entry.get(_CLAUDE_COMPACT_SUMMARY_FIELD) is True:
        return True
    if entry.get("isMeta") is True:
        return True

    origin = entry.get("origin")
    if isinstance(origin, Mapping) and origin.get("kind") == "task-notification":
        return True

    attachment = entry.get("attachment")
    if isinstance(attachment, Mapping):
        if attachment.get("type") == "hook_blocking_error":
            return True
        if attachment.get("commandMode") == "task-notification":
            return True

    if text is None:
        return False

    # Older Claude task-notification transcript entries did not always include
    # origin metadata. The XML wrapper is a Claude CLI envelope, not user prose.
    if entry.get("permissionMode") == "bypassPermissions" and _CLAUDE_TASK_NOTIFICATION_RE.match(text):
        return True

    return _is_teleclaude_control_text(text)


def _is_gemini_internal_user_entry(text: str | None) -> bool:
    """Classify Gemini user-shaped runtime artifacts.

    Gemini session JSON currently stores TeleClaude hook/notification prompts
    as plain user entries with no source metadata, so the exact TeleClaude
    system envelope is the contract available in the native book.
    """
    if text is None:
        return False
    return _is_teleclaude_control_text(text)


def _is_deepseek_internal_user_entry(text: str | None) -> bool:
    """Classify DeepSeek (DSH) user-shaped runtime artifacts.

    DSH transcripts carry harness-injected user entries — the workspace
    ``<system-reminder>`` baseline, runtime-context snapshots, and TeleClaude
    control envelopes — with no source metadata, so the shared injected-text
    classifier is the contract available in the native book.
    """
    if text is None:
        return False
    return _is_teleclaude_control_text(text)


def is_real_user_turn_entry(
    entry: Mapping[str, object],
    agent_name: AgentName | str | None = None,
) -> bool:
    """Return True only for transcript entries that start a real user turn."""
    message = normalize_transcript_entry_message(entry)
    if not isinstance(message, dict) or message.get("role") != "user":
        return False
    if is_user_tool_result_only_message(message):
        return False

    if _agent_value(agent_name) != AgentName.CODEX.value:
        text = extract_text_from_message_content(message.get("content"), _USER_ROLE)
        return text is not None and not is_runtime_artifact_entry(entry, agent_name)
    return bool(_candidate_human_texts(entry, agent_name))


def extract_real_user_text_from_entry(
    entry: Mapping[str, object],
    agent_name: AgentName | str | None = None,
) -> str | None:
    """Return ordered native candidate-human text for one real user turn."""
    if not is_real_user_turn_entry(entry, agent_name):
        return None
    if _agent_value(agent_name) != AgentName.CODEX.value:
        message = normalize_transcript_entry_message(entry)
        if not isinstance(message, Mapping):
            return None
        return extract_text_from_message_content(message.get("content"), _USER_ROLE)
    texts = _candidate_human_texts(entry, agent_name)
    return "\n\n".join(texts) if texts else None


def find_last_real_user_turn(
    entries: Sequence[JsonDict],
    agent_name: AgentName | str | None = None,
) -> RealUserTurn | None:
    """Find the last real user turn in a transcript entry sequence."""
    for i in range(len(entries) - 1, -1, -1):
        entry = entries[i]
        if not is_real_user_turn_entry(entry, agent_name):
            continue
        return RealUserTurn(
            entry_index=i,
            next_index=i + 1,
            text=extract_real_user_text_from_entry(entry, agent_name),
            timestamp=_entry_timestamp(entry),
        )
    return None


def find_turn_start_idx(
    entries: Sequence[JsonDict],
    full_session: bool,
    agent_name: AgentName | str | None = None,
) -> int:
    """Return the first entry index for current-turn transcript inspection."""
    if full_session:
        return 0
    turn = find_last_real_user_turn(entries, agent_name)
    return turn.next_index if turn is not None else 0


__all__ = [
    "ClaudeTurnCommitment",
    "ClaudeTurnCommitmentOutcome",
    "ClaudeTurnCommitmentReason",
    "ClaudeTurnCommitmentResolver",
    "CodexContentItemKind",
    "CodexLegacyShape",
    "CodexStructuralRecognition",
    "CodexStructuralSpan",
    "RealUserTurn",
    "UserContentBlockClassification",
    "UserContentOrigin",
    "classify_user_content_blocks",
    "extract_real_user_text_from_entry",
    "extract_text_from_message_content",
    "find_last_real_user_turn",
    "find_turn_start_idx",
    "is_real_user_turn_entry",
    "is_runtime_artifact_entry",
    "is_runtime_artifact_text",
    "is_user_tool_result_only_message",
    "normalize_runtime_user_text",
    "resolve_claude_turn_commitment",
]
