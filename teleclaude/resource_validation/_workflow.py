"""Corpus-level check of the lifecycle driver declarations across the published procedures.

Each driver procedure declares the phase it drives and the child it dispatches
(``local/projects/teleclaude/spec/feature/workflow/item-lifecycle``). Once any procedure declares a
workflow, every driven phase has exactly one driving procedure and every declared child resolves to
a published procedure with a usable entry.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from teleclaude.entry_declarations import EntryDeclarations
from teleclaude.resource_validation._models import _error
from teleclaude.types.workflow_record import WaitedPhase

DRIVER_SEPARATOR = ", "


class WorkflowFinding(StrEnum):
    """The finding codes of the driver declaration check."""

    PHASE_WITHOUT_DRIVER = "workflow_phase_without_driver"
    PHASE_MULTIPLE_DRIVERS = "workflow_phase_multiple_drivers"
    CHILD_UNRESOLVED = "workflow_child_unresolved"


@dataclass(frozen=True)
class ProcedureRow:
    """A procedure snippet and the entry declarations it carries."""

    snippet_id: str
    path: Path
    entry: EntryDeclarations | None


def validate_workflow_drivers(rows: Iterable[ProcedureRow]) -> None:
    """Report driven phases without exactly one driver, and children that are not usable procedures."""
    usable: dict[str, EntryDeclarations] = {}
    drivers: dict[WaitedPhase, dict[str, Path]] = {phase: {} for phase in WaitedPhase}
    children: dict[str, tuple[Path, str]] = {}
    for row in rows:
        if row.entry is None:
            continue
        usable[row.snippet_id] = row.entry
        if row.entry.workflow is None:
            continue
        drivers[row.entry.workflow.phase][row.snippet_id] = row.path
        children[row.snippet_id] = (row.path, row.entry.workflow.child)
    if not any(drivers.values()):
        return
    for phase, declared in drivers.items():
        if not declared:
            _error(WorkflowFinding.PHASE_WITHOUT_DRIVER.value, phase=phase.value)
        elif len(declared) > 1:
            _error(
                WorkflowFinding.PHASE_MULTIPLE_DRIVERS.value,
                phase=phase.value,
                drivers=DRIVER_SEPARATOR.join(sorted(declared)),
            )
    for path, child in children.values():
        child_entry = usable.get(child)
        if child_entry is None or child_entry.dispatch is None:
            _error(WorkflowFinding.CHILD_UNRESOLVED.value, path=str(path), child=child)
