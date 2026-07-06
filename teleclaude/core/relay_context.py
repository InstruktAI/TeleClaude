"""Platform-neutral admin-relay text sanitization and context compilation."""

from __future__ import annotations

import re


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
        "[Admin Relay Conversation]",
        "The admin spoke directly with the customer. Here is the full exchange:",
        "",
    ]
    for msg in messages:
        content = sanitize_relay_text(msg["content"])
        lines.append(f"{msg['role']} ({msg['name']}): {content}")

    lines.extend(
        [
            "",
            "The admin has handed the conversation back to you. Continue naturally,",
            "acknowledging what was discussed.",
        ]
    )
    return "\n".join(lines)
