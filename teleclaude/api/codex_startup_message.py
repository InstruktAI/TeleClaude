"""Codex startup-message helpers for `/next-*` slash-command sessions."""

from __future__ import annotations

from fastapi import HTTPException

from teleclaude.constants import NON_SLUG_BOUND_COMMANDS
from teleclaude.paths import COMMANDS_DIR

_NON_SLUG_BOUND_VALUES = {command.value for command in NON_SLUG_BOUND_COMMANDS}


def _build_codex_loader_message(command_name: str, args: str) -> str:
    """Build the generic Codex loader message for a compiled prompt file."""
    prompt_path = COMMANDS_DIR / f"{command_name}.md"
    return (
        f"Read {prompt_path} and follow it exactly as the active instruction set for this session.\n\n"
        "Treat the following as provided inputs to that instruction set:\n"
        f"{args}"
    )


def _rewrite_codex_next_startup_message(  # pyright: ignore[reportUnusedFunction]
    startup_message: str, *, effective_agent: str
) -> str:
    """Rewrite Codex `/next-*` startup messages to the loader prompt instruction."""
    if effective_agent != "codex":
        return startup_message

    stripped_message = startup_message.lstrip()
    if not stripped_message.startswith("/next-"):
        return startup_message

    command_token, _, remainder = stripped_message.partition(" ")
    normalized_cmd = command_token.lstrip("/")
    normalized_args = remainder.strip()

    # The `/next-` prefix is a shape, not a command registry: a retired or misspelled
    # token matches it too. Synthesizing a loader for a document that does not exist
    # defers the failure to Codex's first read instead of surfacing it here, so leave
    # the message verbatim for agent-side handling — the behavior the dispatch contract
    # already specifies for an unrecognized command.
    if not (COMMANDS_DIR / f"{normalized_cmd}.md").is_file():
        return startup_message

    if not normalized_args and normalized_cmd not in _NON_SLUG_BOUND_VALUES:
        raise HTTPException(status_code=400, detail=f"/{normalized_cmd} requires a slug argument")
    return _build_codex_loader_message(normalized_cmd, normalized_args)
