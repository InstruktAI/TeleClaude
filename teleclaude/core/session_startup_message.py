"""Core-owned startup-message preparation after agent selection."""

from __future__ import annotations

from teleclaude.constants import NON_SLUG_BOUND_COMMANDS
from teleclaude.paths import COMMANDS_DIR

_NON_SLUG_BOUND_VALUES = {command.value for command in NON_SLUG_BOUND_COMMANDS}


class StartupMessageError(ValueError):
    """A startup message violates the selected runtime's contract."""


def prepare_startup_message(startup_message: str, *, selected_agent: str) -> str:
    """Rewrite recognized Codex next commands only after routing has selected Codex."""
    if selected_agent != "codex":
        return startup_message
    stripped_message = startup_message.lstrip()
    if not stripped_message.startswith("/next-"):
        return startup_message
    command_token, _, remainder = stripped_message.partition(" ")
    command_name = command_token.lstrip("/")
    args = remainder.strip()
    prompt_path = COMMANDS_DIR / f"{command_name}.md"
    if not prompt_path.is_file():
        return startup_message
    if not args and command_name not in _NON_SLUG_BOUND_VALUES:
        raise StartupMessageError(f"/{command_name} requires a slug argument")
    return (
        f"Read {prompt_path} and follow it exactly as the active instruction set for this session.\n\n"
        "Treat the following as provided inputs to that instruction set:\n"
        f"{args}"
    )
