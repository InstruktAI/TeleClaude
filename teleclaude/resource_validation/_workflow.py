"""Corpus-level check of the lifecycle driver declarations across the procedures a publication holds.

Each driver procedure declares the phases it drives and the child it dispatches
(``local/projects/teleclaude/spec/feature/workflow/item-lifecycle``). The check is made per coherent
view of the corpus, never over a raw union of files: the current view holds the live procedures,
and every slug with pending replacements has its own target view in which its companions replace
(or, when empty, retire) their parents. A view that declares drivers is complete: every driven
phase has exactly one driver and every declared child is a procedure of that view with a usable
entry. The current view may declare none while a target view that does is pending; with no view
declaring any, every driven phase lacks a driver.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from teleclaude.entry_declarations import EntryDeclarations, parse_entry_declarations
from teleclaude.resource_validation._markdown import parse_markdown, read_markdown
from teleclaude.resource_validation._models import _error
from teleclaude.snippet_roots import is_excluded_snippet_path
from teleclaude.snippet_validation import (
    SnippetTaxonomy,
    companion_slug,
    derive_snippet_classification,
    is_retirement_companion,
)
from teleclaude.types.workflow_record import DrivenPhase

DRIVER_SEPARATOR: Final = ", "
VIEW_FIELD_CURRENT: Final = "current"
MARKDOWN_GLOB: Final = "*.md"
INDEX_FILENAME: Final = "index.yaml"


class WorkflowFinding(StrEnum):
    """The finding codes of the driver declaration check."""

    PHASE_WITHOUT_DRIVER = "workflow_phase_without_driver"
    PHASE_MULTIPLE_DRIVERS = "workflow_phase_multiple_drivers"
    CHILD_UNRESOLVED = "workflow_child_unresolved"


@dataclass(frozen=True)
class ProcedureRow:
    """A procedure snippet file: its identity, the entry declarations it carries and which delivery it belongs to.

    ``companion_slug`` is the slug of the pending replacement a companion file belongs to, ``None`` for a live
    file. A retirement companion carries no entry and removes its parent from its slug's view.
    """

    snippet_id: str
    path: Path
    entry: EntryDeclarations | None
    companion_slug: str | None = None
    retirement: bool = False


def _view(rows: Iterable[ProcedureRow], slug: str | None) -> dict[str, ProcedureRow]:
    """The procedures of one coherent view: the live files, with one slug's companions applied."""
    materials = list(rows)
    view = {row.snippet_id: row for row in materials if row.companion_slug is None}
    if slug is None:
        return view
    for row in materials:
        if row.companion_slug != slug:
            continue
        if row.retirement:
            view.pop(row.snippet_id, None)
        else:
            view[row.snippet_id] = row
    return view


def _declares_drivers(view: Mapping[str, ProcedureRow]) -> bool:
    return any(row.entry is not None and row.entry.workflow is not None for row in view.values())


def _check_view(view: Mapping[str, ProcedureRow], label: str) -> None:
    """Report the driven phases without exactly one driver, and children that are not usable procedures."""
    drivers: dict[DrivenPhase, list[str]] = {phase: [] for phase in DrivenPhase}
    for snippet_id, row in view.items():
        if row.entry is None or row.entry.workflow is None:
            continue
        for phase in row.entry.workflow.drives:
            drivers[phase].append(snippet_id)
    for phase, declared in drivers.items():
        if not declared:
            _error(WorkflowFinding.PHASE_WITHOUT_DRIVER.value, phase=phase.value, view=label)
        elif len(declared) > 1:
            _error(
                WorkflowFinding.PHASE_MULTIPLE_DRIVERS.value,
                phase=phase.value,
                view=label,
                drivers=DRIVER_SEPARATOR.join(sorted(declared)),
            )
    for row in view.values():
        if row.entry is None or row.entry.workflow is None:
            continue
        child = view.get(row.entry.workflow.child)
        if child is None or child.entry is None or child.entry.dispatch is None:
            _error(
                WorkflowFinding.CHILD_UNRESOLVED.value, path=str(row.path), child=row.entry.workflow.child, view=label
            )


def validate_workflow_drivers(rows: Iterable[ProcedureRow]) -> None:
    """Check the current view and every pending target view, each as a coherent publication."""
    materials = list(rows)
    current = _view(materials, None)
    slugs = sorted({row.companion_slug for row in materials if row.companion_slug is not None})
    targets = {slug: _view(materials, slug) for slug in slugs}
    declaring = {slug: view for slug, view in targets.items() if _declares_drivers(view)}
    if _declares_drivers(current):
        _check_view(current, VIEW_FIELD_CURRENT)
    elif not declaring:
        _check_view(current, VIEW_FIELD_CURRENT)
    for slug, view in declaring.items():
        _check_view(view, slug)


def collect_procedure_rows(
    snippet_roots: Iterable[Path], project_root: Path, domains: Iterable[str]
) -> Sequence[ProcedureRow]:
    """Every procedure snippet file under the roots, companions included, with its entry declarations."""
    known_domains = set(domains)
    rows: list[ProcedureRow] = []
    for snippets_root in snippet_roots:
        for path in sorted(snippets_root.rglob(MARKDOWN_GLOB)):
            if path.name == INDEX_FILENAME or is_excluded_snippet_path(path, snippets_root):
                continue
            classification, _ = derive_snippet_classification(path, project_root=project_root, domains=known_domains)
            if classification is None or classification.type is not SnippetTaxonomy.PROCEDURE:
                continue
            slug = companion_slug(path)
            if is_retirement_companion(path):
                rows.append(ProcedureRow(classification.id, path, None, slug, retirement=True))
                continue
            try:
                metadata = parse_markdown(read_markdown(path)).metadata or {}
            except (OSError, ValueError):
                continue
            rows.append(ProcedureRow(classification.id, path, parse_entry_declarations(metadata).declarations, slug))
    return rows
