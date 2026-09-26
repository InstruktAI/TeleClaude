"""Run-session request shapes and pure command provenance helpers."""

from dataclasses import dataclass

from teleclaude.core.command_input import (
    infer_command_input_metadata,
)
from teleclaude.core.models import SessionEntryPoint, SessionLaunchIntent
from teleclaude.core.models._adapter import TerminalOriginMetadata
from teleclaude.core.session_startup_message import AmbiguousCommandError, resolve_command_document

_COMMAND_PREFIX = "/"


@dataclass(frozen=True)
class RunSessionPlan:
    effective_agent: str | None
    full_command: str
    launch_intent: SessionLaunchIntent
    initiator_session_id: str | None
    origin_metadata: TerminalOriginMetadata | None
    system_role: str | None
    job: str | None
    company: str | None
    command: str
    working_slug: str | None
    entry_point: SessionEntryPoint


def infer_working_slug(command: str, args: str) -> str | None:
    return infer_command_input_metadata(command, args).working_slug


def infer_command_from_message(message: str | None) -> str | None:
    """Return the canonical command name when a launch message carries a leading command.

    A bare token is resolved against the global corpus first, so a
    human-typed unqualified lifecycle command still names its qualified
    value; an ambiguous bare token names no command here rather than
    guessing one.
    """
    if not message or not message.startswith(_COMMAND_PREFIX):
        return None
    bare = message.split()[0].removeprefix(_COMMAND_PREFIX)
    try:
        resolved = resolve_command_document(bare)
    except AmbiguousCommandError:
        return None
    return resolved.canonical_name if resolved is not None else bare


def infer_role_and_slug_from_message(message: str | None) -> tuple[str | None, str | None, str | None]:
    command = infer_command_from_message(message)
    if command is None:
        return None, None, None
    _, _, args = message.partition(" ")
    metadata = infer_command_input_metadata(command, args.strip())
    return metadata.system_role, metadata.job, metadata.working_slug


def leading_command_args(message: str | None) -> str:
    """Return the text following the leading slash command on the message's first line."""
    if not message or not message.startswith(_COMMAND_PREFIX):
        return ""
    return message.partition("\n")[0].partition(" ")[2].strip()
