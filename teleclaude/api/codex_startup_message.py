"""Codex startup-message helpers for `/next-*` slash-command sessions."""

from __future__ import annotations

from fastapi import HTTPException

from teleclaude.paths import COMMANDS_DIR


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
    if not normalized_args:
        raise HTTPException(status_code=400, detail=f"/{normalized_cmd} requires a slug argument")
    return _build_codex_loader_message(normalized_cmd, normalized_args)
