"""Core-owned startup-message preparation after agent selection."""

from __future__ import annotations

from pathlib import Path

from teleclaude.constants import NON_SLUG_BOUND_COMMANDS
from teleclaude.paths import COMMANDS_DIR

_NON_SLUG_BOUND_VALUES = {command.value for command in NON_SLUG_BOUND_COMMANDS}
_COMMAND_PREFIX = "/"
_COMMAND_FILE_SUFFIX = ".md"
_COMMANDS_ROOT = COMMANDS_DIR.resolve()
_COMMAND_MARKER_TEMPLATE = "TELECLAUDE COMMAND: {command}{args}"
_MARKER_ARGUMENT_PREFIX = " "
_LOADER_SECTION_SEPARATOR = "\n\n"
_LOADER_MESSAGE_TEMPLATE = (
    "Read {prompt_path} verbatim and follow it exactly as the active instruction set for this session.\n\n"
    "Treat the following as provided inputs to that instruction set:\n"
    "{args}"
)
_SLUG_REQUIRED_MESSAGE_TEMPLATE = "/{command} requires a slug argument"


class StartupMessageError(ValueError):
    """A startup message violates the selected runtime's contract."""


def resolve_command_document(command_name: str) -> Path | None:
    """Return one containment-safe installed command document, if present."""
    prompt_path = (COMMANDS_DIR / f"{command_name}{_COMMAND_FILE_SUFFIX}").resolve()
    if not prompt_path.is_relative_to(_COMMANDS_ROOT):
        return None
    return prompt_path if prompt_path.is_file() else None


def prepare_startup_message(startup_message: str) -> str:
    """Compose a loader for a recognized command regardless of selected runtime."""
    stripped_message = startup_message.lstrip()
    if not stripped_message.startswith(_COMMAND_PREFIX):
        return startup_message
    command_token, _, remainder = stripped_message.partition(" ")
    command_name = command_token.removeprefix(_COMMAND_PREFIX)
    if not command_name:
        return startup_message
    args = remainder.strip()
    prompt_path = resolve_command_document(command_name)
    if prompt_path is None:
        return startup_message
    if not args and command_name not in _NON_SLUG_BOUND_VALUES:
        raise StartupMessageError(_SLUG_REQUIRED_MESSAGE_TEMPLATE.format(command=command_name))
    marker_args = f"{_MARKER_ARGUMENT_PREFIX}{args}" if args else ""
    return _LOADER_SECTION_SEPARATOR.join(
        (
            _COMMAND_MARKER_TEMPLATE.format(command=command_name, args=marker_args),
            _LOADER_MESSAGE_TEMPLATE.format(prompt_path=prompt_path, args=args),
        )
    )
