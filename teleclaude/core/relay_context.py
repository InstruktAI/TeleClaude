"""Platform-neutral help-desk relay text sanitization and context compilation."""

from __future__ import annotations

import re

_RELAY_CONTEXT_TITLE = "[Help Desk Escalation]"
_RELAY_CONTEXT_INTRO = "A person from the desk's scope spoke directly with the customer. Here is the full exchange:"
_RELAY_CONTEXT_HANDBACK = "A person from the desk's scope has handed the conversation back to you. Continue naturally,"
_RELAY_CONTEXT_CONTINUATION = "acknowledging what was discussed."


def sanitize_relay_text(text: str) -> str:
    """Strip control characters and ANSI escape sequences from relay text."""
    # Remove ANSI escape sequences
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    # Remove other control characters (keep newlines and tabs)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return text


def compile_relay_context(messages: list[dict[str, str]]) -> str:
    """Compile relay messages into a context block for AI injection."""
    lines = [
        _RELAY_CONTEXT_TITLE,
        _RELAY_CONTEXT_INTRO,
        "",
    ]
    for msg in messages:
        content = sanitize_relay_text(msg["content"])
        lines.append(f"{msg['role']} ({msg['name']}): {content}")

    lines.extend(
        [
            "",
            _RELAY_CONTEXT_HANDBACK,
            _RELAY_CONTEXT_CONTINUATION,
        ]
    )
    return "\n".join(lines)
