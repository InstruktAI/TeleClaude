"""Visibility classification for transcript content.

Determines whether user text is system-injected (internal) or genuine human
input. Used by the projection, extraction, and hook layers to filter internal
content from public-facing outputs.
"""

from __future__ import annotations

import re

from teleclaude.constants import TELECLAUDE_SYSTEM_PREFIX

_HOOK_FEEDBACK_PREFIXES = ("Stop hook feedback:", "PreToolUse hook feedback:")

_INTERNAL_WRAPPER_RE = re.compile(
    r"^\s*<(task-notification|system-reminder)\b[^>]*>.*</\1>\s*$",
    re.DOTALL,
)


def is_internal_user_text(text: str) -> bool:
    """Return True if text is system-injected content that must not enter public data fields.

    Detects:
    - TeleClaude system prefix ("[TeleClaude ...")
    - Claude Code hook feedback injections ("Stop hook feedback:", etc.)
    - Claude Code task-notification wrappers (full or prefix)
    - Claude Code system-reminder wrappers (full or prefix)
    """
    stripped = text.lstrip()
    if stripped.startswith(TELECLAUDE_SYSTEM_PREFIX):
        return True
    if stripped.startswith(_HOOK_FEEDBACK_PREFIXES):
        return True
    if stripped.startswith(("<task-notification", "<system-reminder")):
        return True
    if _INTERNAL_WRAPPER_RE.match(text):
        return True
    return False
