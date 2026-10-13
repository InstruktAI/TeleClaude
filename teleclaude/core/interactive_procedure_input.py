"""Interactive command input: a leading procedure ID resolved against the published entry procedures.

The TUI New Session modal and Discord human-to-agent text opt into this shorthand. The leading token is
matched exactly against the published entry procedures by snippet ID; a token that names no usable entry
procedure leaves the text ordinary conversation. A recognized invocation is bound under its procedure's
declared parameters, so what is required and which work item it binds are the procedure's own declaration.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from teleclaude.context_selector import entry_procedure_gap, resolve_snippet_meta
from teleclaude.core.command_input import (
    CommandInputError,
    CommandInputMode,
    CommandInputResult,
    NoCommandInput,
    ResolvedCommandInput,
)
from teleclaude.core.next_machine.lanes import WORKTREE_BOUND_PROCEDURES
from teleclaude.core.procedure_entry import SLUG_PARAMETER, EntryRefusal, bind_parameters, normalize_procedure_id

_LINE_SEPARATOR = "\n"
_ARGUMENT_SEPARATOR = " "
_UNUSABLE_PROCEDURE_TEMPLATE = "{procedure} is not a usable entry procedure"


@dataclass(frozen=True)
class InteractiveBinding:
    """What a recognized invocation binds before any session exists: its declared role and work item."""

    procedure_id: str
    role: str
    working_slug: str | None
    worktree_bound: bool


def resolve_interactive_input(message: str | None, mode: CommandInputMode, project_root: Path) -> CommandInputResult:
    """Resolve opt-in interactive shorthand without changing ordinary chat parsing."""
    if mode is CommandInputMode.ORDINARY or not message:
        return NoCommandInput()
    first_line = message.partition(_LINE_SEPARATOR)[0]
    token, _, raw_args = first_line.partition(_ARGUMENT_SEPARATOR)
    if not token:
        return NoCommandInput()
    try:
        procedure_id = normalize_procedure_id(token)
    except EntryRefusal:
        return NoCommandInput()
    if entry_procedure_gap(resolve_snippet_meta(procedure_id, project_root=project_root)) is not None:
        return NoCommandInput()
    return ResolvedCommandInput(command=procedure_id, args=raw_args.strip())


def bind_interactive_input(resolved: ResolvedCommandInput, project_root: Path) -> InteractiveBinding:
    """Bind a recognized invocation's arguments under the procedure's parameters; a violation is refused visibly."""
    snippet = resolve_snippet_meta(resolved.command, project_root=project_root)
    declarations = snippet.entry.declarations if snippet is not None else None
    if declarations is None:
        raise CommandInputError(_UNUSABLE_PROCEDURE_TEMPLATE.format(procedure=resolved.command))
    try:
        parameters = bind_parameters(resolved.command, declarations.parameters, resolved.args)
    except EntryRefusal as exc:
        raise CommandInputError(exc.detail) from exc
    return InteractiveBinding(
        procedure_id=resolved.command,
        role=declarations.role.name.value,
        working_slug=dict(parameters).get(SLUG_PARAMETER),
        worktree_bound=resolved.command in WORKTREE_BOUND_PROCEDURES,
    )
