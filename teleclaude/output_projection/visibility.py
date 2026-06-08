"""Visibility classification for transcript content.

Three predicates with distinct responsibilities:

- ``is_agent_cli_internal_text`` matches agent-runtime artifacts that have no
  meaning outside the agent CLI that produced them: hook feedback prefixes,
  ``<system-reminder>`` and ``<task-notification>`` wrappers, XML-style
  prefixes. These must never be mirrored to peers, rendered to humans, or
  treated as user input.

- ``is_internal_user_text`` extends the above with the ``[TeleClaude`` prefix
  to support the hook receiver's checkpoint-reset gate: bridge messages
  delivered to a session must NOT be classified as a real user turn that
  resets the checkpoint timer. The ``[TeleClaude`` prefix is *not* a strip
  trigger for projection — brackets are identity markers, not delete cues.

- ``is_hook_side_channel_artifact`` matches the narrower set of hook-side
  artifacts that must not count as typed-in turns.
"""

from __future__ import annotations

import re

from teleclaude.constants import CHECKPOINT_PREFIX, TELECLAUDE_SYSTEM_PREFIX

_HOOK_FEEDBACK_PREFIXES = ("Stop hook feedback:", "PreToolUse hook feedback:")

_INTERNAL_WRAPPER_RE = re.compile(
    r"^\s*<(task-notification|system-reminder)\b[^>]*>.*</\1>\s*$",
    re.DOTALL,
)
_XML_STYLE_PREFIX_RE = re.compile(r"^\s*</?[A-Za-z_][\w:.-]*(?:\s[^>]*)?>", re.DOTALL)


def is_agent_cli_internal_text(text: str) -> bool:
    """Return True when text is an agent-CLI runtime artifact, not real content.

    Detects hook feedback prefixes injected by the agent CLI, XML-style tag
    prefixes, and Claude-style ``<task-notification>`` / ``<system-reminder>``
    wrappers. These are runtime mechanics of a specific agent CLI and have no
    place in peer mirrors or human-facing renders.
    """
    stripped = text.lstrip()
    if stripped.startswith(_HOOK_FEEDBACK_PREFIXES):
        return True
    if _XML_STYLE_PREFIX_RE.match(stripped):
        return True
    if _INTERNAL_WRAPPER_RE.match(text):
        return True
    return False


def is_hook_side_channel_artifact(text: str) -> bool:
    """Return True when text is hook feedback or an agent CLI runtime wrapper."""
    stripped = text.lstrip()
    if stripped.startswith(CHECKPOINT_PREFIX) or stripped.startswith("[TeleClaude Checkpoint]"):
        return True
    return is_agent_cli_internal_text(text)


def is_internal_user_text(text: str) -> bool:
    """Return True when text must not reset checkpoint timing or count as a user turn.

    Used by the hook receiver to gate checkpoint-flag resets. Includes
    ``is_agent_cli_internal_text`` plus the ``[TeleClaude`` prefix — bridge
    messages and other daemon injections share the agent's transcript with
    real user input, but the unified turn timer must only restart on a real
    human prompt.
    """
    stripped = text.lstrip()
    if stripped.startswith(TELECLAUDE_SYSTEM_PREFIX):
        return True
    return is_agent_cli_internal_text(text)
