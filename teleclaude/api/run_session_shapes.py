"""Run-session request shapes and pure command provenance helpers."""

from dataclasses import dataclass

from teleclaude.constants import COMMAND_ROLE_MAP, NON_SLUG_BOUND_COMMANDS, SlashCommand
from teleclaude.core.models import SessionEntryPoint, SessionLaunchIntent
from teleclaude.core.models._adapter import WebOriginMetadata

_SLUG_COMMANDS = {command.value for command in COMMAND_ROLE_MAP if command not in NON_SLUG_BOUND_COMMANDS}
_SLUG_COMMANDS.add("analyze-todo-input")
_WORKING_SLUG_COMMANDS = _SLUG_COMMANDS | {SlashCommand.NEXT_PREPARE.value}


@dataclass(frozen=True)
class RunSessionPlan:
    effective_agent: str | None
    full_command: str
    launch_intent: SessionLaunchIntent
    initiator_session_id: str | None
    origin_metadata: WebOriginMetadata | None
    system_role: str | None
    job: str | None
    working_slug: str | None
    entry_point: SessionEntryPoint


def infer_working_slug(command: str, args: str) -> str | None:
    if command not in _WORKING_SLUG_COMMANDS:
        return None
    return args.partition(" ")[0].strip() or None


def infer_role_and_slug_from_message(message: str | None) -> tuple[str | None, str | None, str | None]:
    if not message or not message.startswith("/"):
        return None, None, None
    command, _, args = message.partition(" ")
    command = command.lstrip("/")
    slug = infer_working_slug(command, args.strip())
    try:
        role_info = COMMAND_ROLE_MAP.get(SlashCommand(command))
    except ValueError:
        role_info = None
    return (role_info[0], role_info[1].value, slug) if role_info else (None, None, slug)
