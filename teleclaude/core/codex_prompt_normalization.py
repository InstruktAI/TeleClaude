"""Codex prompt command normalization helpers."""

from __future__ import annotations

from typing import Optional

from teleclaude.core.agents import AgentName

_PROMPTS_PREFIX = "/prompts:"
_PROMPT_PREFIX = "/prompt:"
_NEXT_PREFIX = "/next-"


def normalize_codex_next_command(agent_name: Optional[str], text: str) -> str:
    """Normalize Codex /next-* commands to the prompts namespace.

    Codex custom prompts are invoked with a prompt namespace command. We only
    normalize `/next-*` commands so built-in slash commands remain unchanged.
    """
    if not text:
        return text
    if (agent_name or "").strip().lower() != AgentName.CODEX.value:
        return text

    stripped = text.lstrip()
    if not stripped.startswith(_NEXT_PREFIX):
        return text

    first_token = stripped.split(maxsplit=1)[0]
    if first_token.startswith(_PROMPTS_PREFIX) or first_token.startswith(_PROMPT_PREFIX):
        return text

    command_name = first_token[1:]
    if not command_name:
        return text

    prefix_len = len(text) - len(stripped)
    suffix = stripped[len(first_token) :]
    return f"{text[:prefix_len]}{_PROMPTS_PREFIX}{command_name}{suffix}"
