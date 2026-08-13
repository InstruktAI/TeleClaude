"""Visibility classification for transcript content.

Three predicates with distinct responsibilities:

- ``is_agent_cli_internal_text`` matches agent-runtime artifacts that have no
  meaning outside the agent CLI that produced them: hook feedback prefixes,
  ``<system-reminder>`` and ``<task-notification>`` wrappers, XML-style
  prefixes, complete ``<teammate-message>`` blocks, and a leading
  ``# AGENTS.md instructions`` heading (bare or directory-qualified). These
  must never be mirrored to peers, rendered to humans, or treated as user
  input.

- ``is_internal_user_text`` extends the above with the ``[TeleClaude`` prefix
  to identify daemon injections that must not be classified as real user
  turns. The ``[TeleClaude`` prefix is *not* a strip trigger for projection —
  brackets are identity markers, not delete cues.

- ``is_hook_side_channel_artifact`` matches the narrower set of hook-side
  artifacts that must not count as typed-in turns.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType

from teleclaude.constants import CHECKPOINT_PREFIX, TELECLAUDE_SYSTEM_PREFIX
from teleclaude.core.conversation_messages import (
    TELECLAUDE_NOTIFICATION_LABELS,
    MachineRoleLabel,
    TeleClaudeNotificationLabel,
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

# Peer-bridge blocks carry no MachineRoleLabel of their own — the resolver
# names them with the header's own category token.
_PEER_BRIDGE_LABEL = "Peer"

_NOTIFICATION_PREFIX_TEMPLATE = "[TeleClaude {label}]"
_SYSTEM_MESSAGE_PREFIX_TEMPLATE = "[{label} "

_NOTIFICATION_PREFIXES: Mapping[str, TeleClaudeNotificationLabel] = MappingProxyType(
    {_NOTIFICATION_PREFIX_TEMPLATE.format(label=label): label for label in TELECLAUDE_NOTIFICATION_LABELS}
)
_SYSTEM_MESSAGE_PREFIXES: Mapping[str, MachineRoleLabel] = MappingProxyType(
    {_SYSTEM_MESSAGE_PREFIX_TEMPLATE.format(label=label): label for label in MachineRoleLabel}
)

_INTERNAL_WRAPPER_RE = re.compile(
    r"^\s*<(task-notification|system-reminder)\b[^>]*>.*</\1>\s*$",
    re.DOTALL,
)
_TEAMMATE_MESSAGE_BLOCK_RE = re.compile(
    r"<teammate-message\b[^>]*>.*?</teammate-message\s*>",
    re.DOTALL,
)
_XML_STYLE_PREFIX_RE = re.compile(r"^\s*</?[A-Za-z_][\w:.-]*(?:\s[^>]*)?>", re.DOTALL)
_AGENTS_MD_INSTRUCTIONS_RE = re.compile(r"^# AGENTS\.md instructions(?: for .*)?[ \t]*(?:\r?\n|$)")


def is_agent_cli_internal_text(text: str) -> bool:
    """Return True when text is an agent-CLI runtime artifact, not real content.

    Detects hook feedback prefixes injected by the agent CLI, XML-style tag
    prefixes, Claude-style ``<task-notification>`` / ``<system-reminder>``
    wrappers, complete ``<teammate-message>`` blocks, and a leading
    ``# AGENTS.md instructions`` heading (bare or directory-qualified, as
    emitted by the codex CLI). These are runtime mechanics of a specific
    agent CLI and have no place in peer mirrors or human-facing renders.
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
    if _AGENTS_MD_INSTRUCTIONS_RE.match(stripped):
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


def resolve_projected_text_author(text: str) -> tuple[ProjectedTextCategory, str | None]:
    """Classify text and return the category together with its matched machine label.

    The label is the specific ``MachineRoleLabel`` / ``TeleClaudeNotificationLabel``
    value that matched, or the peer-bridge marker for a cross-shared segment.
    ``None`` for ``SIDE_CHANNEL`` (never emitted) and ``ORDINARY`` (human-authored,
    no machine identity to resolve). This is the sole classification owner —
    ``classify_projected_text`` is a thin projection of its category.
    """
    stripped = text.lstrip()
    if is_hook_side_channel_artifact(stripped):
        return ProjectedTextCategory.SIDE_CHANNEL, None
    # is_conversation_bridge_message recognizes the leading structural marker
    # only — never the full peer grammar. It is the one part of the historical
    # bridge format that never froze delivery (see conversation_messages'
    # MalformedPeerSegmentError). Authorship for a bridge-classified block is
    # a durable, structural fact (peer bundle segments) once a bundle exists
    # for it; this classification decides presentation only — which category
    # badge a human sees — never attribution.
    if is_conversation_bridge_message(stripped):
        return ProjectedTextCategory.PEER_CROSS_SHARE, _PEER_BRIDGE_LABEL
    for prefix, notification_label in _NOTIFICATION_PREFIXES.items():
        if stripped.startswith(prefix):
            return ProjectedTextCategory.NOTIFICATION, notification_label.value
    for prefix, role_label in _SYSTEM_MESSAGE_PREFIXES.items():
        if stripped.startswith(prefix):
            return ProjectedTextCategory.SYSTEM_MESSAGE, role_label.value
    return ProjectedTextCategory.ORDINARY, None


def classify_projected_text(text: str) -> ProjectedTextCategory:
    """Classify deterministic bracket markers for projected user text."""
    category, _ = resolve_projected_text_author(text)
    return category
