"""Corpus-level check of the lifecycle driver declarations across the procedures a publication holds.

Each driver procedure declares the phases it drives and the child it dispatches
(``local/projects/teleclaude/spec/feature/workflow/item-lifecycle``). The check is made per coherent
view of the corpus, never over a raw union of files. The current view holds the procedures that
are live; every slug with pending material has its own target view in which its companions replace
(or, when empty, retire) their parents and its brand-new procedures appear. A view that declares
drivers is complete: every driven phase has exactly one driver and every declared child is a
procedure of that view with a usable entry.

Whether a view must declare drivers is decided by the contract in that view: where the
item-lifecycle spec is itself live, the lifecycle machine governs and the view is checked whatever
pending material exists, so a target that removes every driver is checked too. Where the spec is
still pending, or a target retires it, the machine is being staged and a view is checked only when it
declares drivers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from teleclaude.entry_declarations import EntryDeclarations, WorkflowDeclaration, parse_entry_declarations
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
WORKFLOW_AUTHORITY_ID: Final = "local/projects/teleclaude/spec/feature/workflow/item-lifecycle"
MARKDOWN_GLOB: Final = "*.md"
INDEX_FILENAME: Final = "index.yaml"
DELIVERED_BY_KEY: Final = "delivered_by"


class WorkflowFinding(StrEnum):
    """The finding codes of the driver declaration check."""

    PHASE_WITHOUT_DRIVER = "workflow_phase_without_driver"
    PHASE_MULTIPLE_DRIVERS = "workflow_phase_multiple_drivers"
    CHILD_UNRESOLVED = "workflow_child_unresolved"


@dataclass(frozen=True)
class ProcedureRow:
    """A procedure snippet file: its identity, the entry declarations it carries and which delivery it belongs to.

    ``companion_slug`` is the slug of the pending replacement a companion file belongs to, ``None`` for a live
    file. A retirement companion carries no entry and removes its parent from its slug's view. ``delivered_by``
    names the deliveries a brand-new, not yet live procedure belongs to.
    """

    snippet_id: str
    path: Path
    entry: EntryDeclarations | None
    companion_slug: str | None = None
    retirement: bool = False
    delivered_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class AuthorityRow:
    """A file of the snippet that makes the lifecycle machine govern: its pending carrier, if any."""

    companion_slug: str | None = None
    retirement: bool = False
    delivered_by: tuple[str, ...] = ()


@dataclass(frozen=True)
class WorkflowCorpus:
    """The procedure files of a publication and the files of the contract that makes the machine govern."""

    rows: Sequence[ProcedureRow]
    authority: Sequence[AuthorityRow]


def _governs(authority: Iterable[AuthorityRow], slug: str | None) -> bool:
    """Whether the lifecycle contract is live in one view: the current one, or one delivery's target."""
    live = False
    for row in authority:
        if row.companion_slug is None and not row.delivered_by:
            live = True
    if slug is None:
        return live
    for row in authority:
        if row.companion_slug == slug:
            live = not row.retirement
        elif row.companion_slug is None and slug in row.delivered_by:
            live = True
    return live


def _view(rows: Iterable[ProcedureRow], slug: str | None) -> dict[str, ProcedureRow]:
    """The procedures of one coherent view: the live ones, with one delivery's pending material applied."""
    materials = list(rows)
    view = {row.snippet_id: row for row in materials if row.companion_slug is None and not row.delivered_by}
    if slug is None:
        return view
    for row in materials:
        if row.companion_slug == slug:
            if row.retirement:
                view.pop(row.snippet_id, None)
            else:
                view[row.snippet_id] = row
        elif row.companion_slug is None and slug in row.delivered_by:
            view[row.snippet_id] = row
    return view


def _declares_drivers(view: Mapping[str, ProcedureRow]) -> bool:
    return any(row.entry is not None and row.entry.workflow is not None for row in view.values())


def _declared_children(workflow: WorkflowDeclaration) -> list[str]:
    """The children a driver declares, at the procedure level and in its scopes, without repeats."""
    names = [workflow.child, *(scope.child for scope in workflow.scopes)]
    return sorted({name for name in names if name is not None})


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
        for child_id in _declared_children(row.entry.workflow):
            child = view.get(child_id)
            if child is None or child.entry is None or child.entry.dispatch is None:
                _error(WorkflowFinding.CHILD_UNRESOLVED.value, path=str(row.path), child=child_id, view=label)


def validate_workflow_drivers(corpus: WorkflowCorpus) -> None:
    """Check the current view and every pending target view, each as a coherent publication."""
    materials = list(corpus.rows)
    current = _view(materials, None)
    slugs = sorted(
        {row.companion_slug for row in materials if row.companion_slug is not None}
        | {slug for row in materials for slug in row.delivered_by}
        | {row.companion_slug for row in corpus.authority if row.companion_slug is not None}
        | {slug for row in corpus.authority for slug in row.delivered_by}
    )
    if _governs(corpus.authority, None) or _declares_drivers(current):
        _check_view(current, VIEW_FIELD_CURRENT)
    for slug in slugs:
        view = _view(materials, slug)
        if _governs(corpus.authority, slug) or _declares_drivers(view):
            _check_view(view, slug)


def collect_procedure_rows(snippet_roots: Iterable[Path], project_root: Path, domains: Iterable[str]) -> WorkflowCorpus:
    """Every procedure snippet file under the roots, companions included, and the files of the governing contract."""
    known_domains = set(domains)
    rows: list[ProcedureRow] = []
    authority: list[AuthorityRow] = []
    for snippets_root in snippet_roots:
        for path in sorted(snippets_root.rglob(MARKDOWN_GLOB)):
            if path.name == INDEX_FILENAME or is_excluded_snippet_path(path, snippets_root):
                continue
            classification, _ = derive_snippet_classification(path, project_root=project_root, domains=known_domains)
            if classification is None:
                continue
            slug = companion_slug(path)
            if classification.id == WORKFLOW_AUTHORITY_ID:
                authority.append(
                    AuthorityRow(slug, is_retirement_companion(path), _delivered_by(path) if slug is None else ())
                )
            if classification.type is not SnippetTaxonomy.PROCEDURE:
                continue
            if is_retirement_companion(path):
                rows.append(ProcedureRow(classification.id, path, None, slug, retirement=True))
                continue
            metadata = _metadata(path)
            if metadata is None:
                continue
            rows.append(
                ProcedureRow(
                    classification.id,
                    path,
                    parse_entry_declarations(metadata).declarations,
                    slug,
                    delivered_by=_slugs(metadata.get(DELIVERED_BY_KEY)),
                )
            )
    return WorkflowCorpus(rows=rows, authority=authority)


def _metadata(path: Path) -> Mapping[str, object] | None:
    try:
        return parse_markdown(read_markdown(path)).metadata or {}
    except (OSError, ValueError):
        return None


def _slugs(raw: object) -> tuple[str, ...]:
    return tuple(item for item in raw if isinstance(item, str)) if isinstance(raw, list) else ()


def _delivered_by(path: Path) -> tuple[str, ...]:
    metadata = _metadata(path)
    return _slugs(metadata.get(DELIVERED_BY_KEY)) if metadata is not None else ()
