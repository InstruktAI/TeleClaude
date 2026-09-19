"""Core-owned startup-message preparation after agent selection."""

from __future__ import annotations

from pathlib import Path

from teleclaude.core.command_input import (
    CommandInputError,
    CommandInputMode,
    CommandInputResult,
    NoCommandInput,
    RefusedCommandInput,
    ResolvedCommandInput,
    normalize_command_input_token,
)
from teleclaude.core.models import SessionDispatchDoor
from teleclaude.paths import COMMANDS_DIR

_COMMAND_PREFIX = "/"
_COMMAND_FILE_SUFFIX = ".md"
_COMMANDS_ROOT = COMMANDS_DIR.resolve()
_COMMAND_MARKER_TEMPLATE = "TELECLAUDE COMMAND: {command}{args}"
_DISPATCH_DOOR_TEMPLATE = "DISPATCH DOOR: {dispatch_door}"
_MARKER_ARGUMENT_PREFIX = " "
_LOADER_SECTION_SEPARATOR = "\n\n"
_LINE_SEPARATOR = "\n"
_COMMAND_ARGUMENT_SEPARATOR = " "
_LOADER_MESSAGE_TEMPLATE = (
    "Read {prompt_path} verbatim and follow it exactly as the active instruction set for this session.\n\n"
    "Treat the following as provided inputs to that instruction set:\n"
    "{args}"
)
_UNKNOWN_COMMAND_MESSAGE_TEMPLATE = "/{command} resolves to no installed command document"


class StartupMessageError(ValueError):
    """A startup message violates the selected runtime's contract."""


def resolve_command_document(command_name: str) -> Path | None:
    """Return one containment-safe installed command document, if present."""
    prompt_path = (COMMANDS_DIR / f"{command_name}{_COMMAND_FILE_SUFFIX}").resolve()
    if not prompt_path.is_relative_to(_COMMANDS_ROOT):
        return None
    return prompt_path if prompt_path.is_file() else None


def compose_command_loader(
    command_name: str,
    args: str,
    dispatch_door: SessionDispatchDoor | None = None,
) -> str:
    """Compose the loader for an already-resolved command name and its arguments.

    Raises when the command resolves to no installed document. Argument
    admissibility is the dispatch door's rule, not this function's — it
    parses nothing and gates nothing but document existence.
    """
    prompt_path = resolve_command_document(command_name)
    if prompt_path is None:
        raise StartupMessageError(_UNKNOWN_COMMAND_MESSAGE_TEMPLATE.format(command=command_name))
    marker_args = f"{_MARKER_ARGUMENT_PREFIX}{args}" if args else ""
    metadata = _DISPATCH_DOOR_TEMPLATE.format(dispatch_door=dispatch_door.value) if dispatch_door is not None else ""
    return _LOADER_SECTION_SEPARATOR.join(
        section
        for section in (
            _COMMAND_MARKER_TEMPLATE.format(command=command_name, args=marker_args),
            metadata,
            _LOADER_MESSAGE_TEMPLATE.format(prompt_path=prompt_path, args=args),
        )
        if section
    )


def resolve_command_input(message: str | None, mode: CommandInputMode) -> CommandInputResult:
    """Resolve opt-in interactive shorthand without changing ordinary chat parsing."""
    if mode is CommandInputMode.ORDINARY or not message:
        return NoCommandInput()
    first_line = message.partition(_LINE_SEPARATOR)[0]
    command_token, _, raw_args = first_line.partition(_COMMAND_ARGUMENT_SEPARATOR)
    if not command_token:
        return NoCommandInput()
    try:
        command_name = normalize_command_input_token(command_token)
    except CommandInputError as exc:
        if command_token.startswith(_COMMAND_PREFIX):
            return RefusedCommandInput(detail=str(exc))
        return NoCommandInput()
    if resolve_command_document(command_name) is None:
        return NoCommandInput()
    return ResolvedCommandInput(command=command_name, args=raw_args.strip())


def prepare_startup_message(
    startup_message: str,
    declared_command: str | None,
    dispatch_door: SessionDispatchDoor | None = None,
) -> str:
    """Compose a loader for a dispatched session, from the message's first line only.

    With ``declared_command``, compose from that command and the arguments
    following it on the first line, then re-append everything after the
    first line unchanged; a command that resolves to no installed document
    raises rather than passing the raw text through. With no declared
    command, keep chat's permissive behavior: resolve the first line's
    leading token against the installed command corpus and pass the message
    through unchanged when it does not resolve.
    """
    stripped_message = startup_message.lstrip()
    first_line, _, trailing = stripped_message.partition("\n")
    trailing = trailing.strip("\n")
    if declared_command is None:
        if not first_line.startswith(_COMMAND_PREFIX):
            return startup_message
        command_token, _, first_line_args = first_line.partition(" ")
        command_name = command_token.removeprefix(_COMMAND_PREFIX)
        if not command_name or resolve_command_document(command_name) is None:
            return startup_message
        args = first_line_args.strip()
    else:
        command_name = declared_command
        _, _, first_line_args = first_line.partition(" ")
        args = first_line_args.strip()
    composed = compose_command_loader(command_name, args, dispatch_door)
    if trailing:
        composed = f"{composed}{_LOADER_SECTION_SEPARATOR}{trailing}"
    return composed
