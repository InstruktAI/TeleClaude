"""Typed command-input intent shared by interactive transport edges."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from teleclaude.cli.telec.auth import is_command_allowed
from teleclaude.constants import COMMAND_ROLE_MAP, NON_SLUG_BOUND_COMMANDS, SlashCommand

_COMMAND_SEGMENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_COMMAND_SEPARATOR = "/"
_COMMAND_INPUT_SEPARATOR = " "
_ORDINARY_INPUT_MODE = "ordinary"
_INTERACTIVE_SHORTHAND_INPUT_MODE = "interactive_shorthand"
_INVALID_COMMAND_TEMPLATE = "invalid command: {command}"
_NORMALIZED_COMMAND_TEMPLATE = "/{command}"
_NORMALIZED_COMMAND_WITH_ARGS_TEMPLATE = "/{command} {args}"
_ANALYZE_TODO_INPUT_COMMAND = "analyze-todo-input"
_NEXT_PREPARE_COMMAND = SlashCommand.NEXT_PREPARE.value
_NEXT_DEFER_COMMAND = SlashCommand.NEXT_DEFER.value
_NEXT_PREPARE_INVESTIGATE_COMMAND = "next-prepare-investigate"
_NEXT_RESEARCH_COMMAND = "next-research"
_NEXT_RUN_JOB_COMMAND = SlashCommand.NEXT_RUN_JOB.value
_SESSIONS_RUN_COMMAND = "telec sessions run"
_COMMAND_INPUT_CLEARANCE_DETAIL = "caller is not permitted to invoke command input"
_MISSING_ARGUMENT_TEMPLATE = "/{command} requires a slug argument"
_JOB_COMMAND_GENERIC_CREATE_DETAIL = "next-run-job must be dispatched through /sessions/run"


class CommandInputMode(StrEnum):
    """Whether an ingress explicitly opts into interactive command shorthand."""

    ORDINARY = _ORDINARY_INPUT_MODE
    INTERACTIVE_SHORTHAND = _INTERACTIVE_SHORTHAND_INPUT_MODE


class CommandInputError(ValueError):
    """A command-shaped interactive input violates the command-token contract."""


@dataclass(frozen=True)
class NoCommandInput:
    """The input remains ordinary conversation."""


@dataclass(frozen=True)
class ResolvedCommandInput:
    """One installed command invocation, normalized for command consumers."""

    command: str
    args: str

    @property
    def normalized_message(self) -> str:
        """Return the canonical slash-prefixed command line."""
        if self.args:
            return _NORMALIZED_COMMAND_WITH_ARGS_TEMPLATE.format(command=self.command, args=self.args)
        return _NORMALIZED_COMMAND_TEMPLATE.format(command=self.command)


@dataclass(frozen=True)
class RefusedCommandInput:
    """A command-shaped input that must surface a typed admission refusal."""

    detail: str


CommandInputResult = NoCommandInput | ResolvedCommandInput | RefusedCommandInput

_SLUG_COMMANDS = frozenset(command.value for command in COMMAND_ROLE_MAP if command not in NON_SLUG_BOUND_COMMANDS)
WORKING_SLUG_COMMANDS = _SLUG_COMMANDS | {_ANALYZE_TODO_INPUT_COMMAND, _NEXT_PREPARE_COMMAND}
SLUG_REQUIRED_LIFECYCLE_COMMANDS = _SLUG_COMMANDS - frozenset(command.value for command in NON_SLUG_BOUND_COMMANDS)
REQUIRED_ARGUMENT_NON_LIFECYCLE_COMMANDS = frozenset(
    {_NEXT_DEFER_COMMAND, _NEXT_PREPARE_INVESTIGATE_COMMAND, _NEXT_RESEARCH_COMMAND}
)
WORKTREE_BOUND_WORKER_COMMANDS = frozenset(
    {SlashCommand.NEXT_BUILD, SlashCommand.NEXT_REVIEW_BUILD, SlashCommand.NEXT_FINALIZE}
)


@dataclass(frozen=True)
class CommandInputMetadata:
    """Canonical role, job, and work-item metadata for one resolved command."""

    system_role: str | None
    job: str | None
    working_slug: str | None


def normalize_command_input_token(command: str) -> str:
    """Validate one command token while accepting its optional leading slash."""
    has_leading_slash = command.startswith(_COMMAND_SEPARATOR)
    candidate = command.removeprefix(_COMMAND_SEPARATOR)
    segments = candidate.split(_COMMAND_SEPARATOR)
    valid_segments = all(_COMMAND_SEGMENT_PATTERN.fullmatch(segment) for segment in segments)
    accepts_shape = len(segments) == 1 or (len(segments) == 2 and not has_leading_slash)
    if not accepts_shape or not valid_segments:
        raise CommandInputError(_INVALID_COMMAND_TEMPLATE.format(command=command))
    return candidate


def infer_command_input_metadata(command: str, args: str) -> CommandInputMetadata:
    """Derive command-owned session metadata without interpreting natural language."""
    working_slug = args.partition(_COMMAND_INPUT_SEPARATOR)[0].strip() if command in WORKING_SLUG_COMMANDS else None
    try:
        role_info = COMMAND_ROLE_MAP.get(SlashCommand(command))
    except ValueError:
        role_info = None
    if role_info is None:
        return CommandInputMetadata(system_role=None, job=None, working_slug=working_slug)
    return CommandInputMetadata(system_role=role_info[0], job=role_info[1].value, working_slug=working_slug)


def admit_command_input(command: str, args: str, human_role: str | None) -> CommandInputMetadata:
    """Apply shared interactive command admission before composing its loader."""
    if not is_command_allowed(_SESSIONS_RUN_COMMAND, None, human_role):
        raise CommandInputError(_COMMAND_INPUT_CLEARANCE_DETAIL)
    metadata = infer_command_input_metadata(command, args)
    if command == _NEXT_RUN_JOB_COMMAND:
        raise CommandInputError(_JOB_COMMAND_GENERIC_CREATE_DETAIL)
    if command in REQUIRED_ARGUMENT_NON_LIFECYCLE_COMMANDS and not args:
        raise CommandInputError(_MISSING_ARGUMENT_TEMPLATE.format(command=command))
    if command in SLUG_REQUIRED_LIFECYCLE_COMMANDS and not metadata.working_slug:
        raise CommandInputError(_MISSING_ARGUMENT_TEMPLATE.format(command=command))
    return metadata
