"""Visibility classification for transcript content.

Three predicates with distinct responsibilities:

- ``is_agent_cli_internal_text`` matches agent-runtime artifacts that have no
  meaning outside the agent CLI that produced them: hook feedback prefixes,
  ``<system-reminder>`` and ``<task-notification>`` wrappers, XML-style
  prefixes, and complete ``<teammate-message>`` blocks. These must never be
  mirrored to peers, rendered to humans, or treated as user input.

- ``is_internal_user_text`` extends the above with the ``[TeleClaude`` prefix
  to identify daemon injections that must not be classified as real user
  turns. The ``[TeleClaude`` prefix is *not* a strip trigger for projection —
  brackets are identity markers, not delete cues.

- ``is_hook_side_channel_artifact`` matches the narrower set of hook-side
  artifacts that must not count as typed-in turns.
"""

from __future__ import annotations

import re
from enum import StrEnum

from teleclaude.constants import CHECKPOINT_PREFIX, TELECLAUDE_SYSTEM_PREFIX
from teleclaude.core.conversation_messages import (
    TELECLAUDE_NOTIFICATION_LABELS,
    MachineRoleLabel,
    is_conversation_bridge_message,
)


class ProjectedTextCategory(StrEnum):
    """Deterministic projection category for leading bracket-marked text."""

    ORDINARY = "ordinary"
    PEER_CROSS_SHARE = "peer_cross_share"
    NOTIFICATION = "notification"
    SYSTEM_MESSAGE = "system_message"
    SIDE_CHANNEL = "side_channel"


_HOOK_FEEDBACK_PREFIXES = ("Stop hook feedback:", "PreToolUse hook feedback:")
_NOTIFICATION_PREFIXES = tuple(f"[TeleClaude {label}]" for label in TELECLAUDE_NOTIFICATION_LABELS)
_SYSTEM_MESSAGE_PREFIXES = tuple(f"[{label} " for label in MachineRoleLabel)

_INTERNAL_WRAPPER_RE = re.compile(
    r"^\s*<(task-notification|system-reminder)\b[^>]*>.*</\1>\s*$",
    re.DOTALL,
)
_TEAMMATE_MESSAGE_BLOCK_RE = re.compile(
    r"<teammate-message\b[^>]*>.*?</teammate-message\s*>",
    re.DOTALL,
)
_XML_STYLE_PREFIX_RE = re.compile(r"^\s*</?[A-Za-z_][\w:.-]*(?:\s[^>]*)?>", re.DOTALL)


def is_agent_cli_internal_text(text: str) -> bool:
    """Return True when text is an agent-CLI runtime artifact, not real content.

    Detects hook feedback prefixes injected by the agent CLI, XML-style tag
    prefixes, Claude-style ``<task-notification>`` / ``<system-reminder>``
    wrappers, and complete ``<teammate-message>`` blocks. These are runtime
    mechanics of a specific agent CLI and have no place in peer mirrors or
    human-facing renders.
    """
    stripped = text.lstrip()
    if stripped.startswith(_HOOK_FEEDBACK_PREFIXES):
        return True
    if _XML_STYLE_PREFIX_RE.match(stripped):
        return True
    if _INTERNAL_WRAPPER_RE.match(text):
        return True
    if _TEAMMATE_MESSAGE_BLOCK_RE.search(text):
        return True
    return False


def is_hook_side_channel_artifact(text: str) -> bool:
    """Return True when text is hook feedback or an agent CLI runtime wrapper."""
    stripped = text.lstrip()
    if stripped.startswith(CHECKPOINT_PREFIX) or stripped.startswith("[TeleClaude Checkpoint]"):
        return True
    return is_agent_cli_internal_text(text)


def is_internal_user_text(text: str) -> bool:
    """Return True when text is internal rather than a real user turn.

    This retained predicate extends ``is_agent_cli_internal_text`` with the
    ``[TeleClaude`` prefix, which identifies daemon-injected messages sharing
    a transcript with real user input.
    """
    stripped = text.lstrip()
    if stripped.startswith(TELECLAUDE_SYSTEM_PREFIX):
        return True
    return is_agent_cli_internal_text(text)


def classify_projected_text(text: str) -> ProjectedTextCategory:
    """Classify deterministic bracket markers for projected user text."""
    stripped = text.lstrip()
    if is_hook_side_channel_artifact(stripped):
        return ProjectedTextCategory.SIDE_CHANNEL
    if is_conversation_bridge_message(stripped):
        return ProjectedTextCategory.PEER_CROSS_SHARE
    if stripped.startswith(_NOTIFICATION_PREFIXES):
        return ProjectedTextCategory.NOTIFICATION
    if stripped.startswith(_SYSTEM_MESSAGE_PREFIXES):
        return ProjectedTextCategory.SYSTEM_MESSAGE
    return ProjectedTextCategory.ORDINARY
