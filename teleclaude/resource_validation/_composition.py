"""Procedure composition across the validated home and the published documentation.

Two rules hold across deliveries, which no single delivery's review sees
(``general/spec/snippet-authoring-schema``, Root frontmatter):

* a ``role`` value is declared by one procedure only;
* an entry procedure's Required reads never name a procedure of the group folder
  it heads that carries no root frontmatter, which is its sub-procedure.

Both read declared structure only: frontmatter keys, Required-read targets and
folder membership. No step judges body prose.
"""

from __future__ import annotations

import glob
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml

from teleclaude.docs_publishers import DocsPublisherResolutionError, project_slug
from teleclaude.docs_subscriptions import (
    IndexKey,
    published_index_path,
    read_published_snippets,
    tier_source_project,
)
from teleclaude.entry_declarations import EntryKey
from teleclaude.paths import GLOBAL_DOCS_ROOTS
from teleclaude.required_reads import extract_required_reads
from teleclaude.resource_validation._markdown import parse_markdown, read_markdown
from teleclaude.resource_validation._models import _error
from teleclaude.resource_validation._refs import resolve_ref_path
from teleclaude.snippet_roots import iter_snippet_roots, snippet_files
from teleclaude.snippet_validation import (
    SnippetTaxonomy,
    companion_slug,
    derive_snippet_classification,
    is_retirement_companion,
    tier_root_kind,
)

_DOCS_DIRNAME = "docs"
_MARKDOWN_SUFFIX = ".md"
_COMPANION_GLOB = "{stem}.*.md"
_ID_SEPARATOR = "/"
_OVERVIEW_SEGMENT = "overview"
_FRONTMATTER_FENCE = "---"
_LIST_SEPARATOR = ", "
_READ_FAILED_FINDING = "snippet_read_failed"

#: A procedure carrying any of these with a value is an entry procedure: a session is started into it.
_ROOT_FRONTMATTER_KEYS = (
    EntryKey.ROLE,
    IndexKey.SUBSCRIPTIONS,
    IndexKey.ACTIVATION_TRIGGER,
    EntryKey.DISPATCH,
)


class CompositionFinding(StrEnum):
    """The finding codes the composition pass reports."""

    ROLE_SHARED = "snippet_procedure_role_shared"
    SUBPROCEDURE_REQUIRED = "snippet_procedure_subprocedure_required"
    PUBLISHED_INDEX_UNREADABLE = "snippet_published_index_unreadable"


@dataclass(frozen=True)
class _ProcedureState:
    """One state of a procedure: its live file, or one non-empty pending companion."""

    procedure_id: str
    path: Path
    in_home: bool
    has_root_frontmatter: bool
    role: str | None
    required_ids: frozenset[str]


@dataclass(frozen=True)
class _HomeSource:
    """A directory of home snippets and the root its files classify against."""

    snippets_root: Path
    classification_root: Path


Corpus = Mapping[str, tuple[_ProcedureState, ...]]


def _is_overview(procedure_id: str) -> bool:
    return procedure_id.rpartition(_ID_SEPARATOR)[2] == _OVERVIEW_SEGMENT


def _group_folder(procedure_id: str) -> str:
    return procedure_id.rpartition(_ID_SEPARATOR)[0]


def _has_root_frontmatter(metadata: Mapping[str, object]) -> bool:
    return any(metadata.get(key) is not None for key in _ROOT_FRONTMATTER_KEYS)


def _declared_role(metadata: Mapping[str, object]) -> str | None:
    role = metadata.get(EntryKey.ROLE)
    return role if isinstance(role, str) and role else None


def _frontmatter(text: str) -> Mapping[str, object]:
    """The root frontmatter of a source image; unparseable frontmatter declares nothing."""
    if not text.lstrip().startswith(_FRONTMATTER_FENCE):
        return {}
    try:
        return parse_markdown(text).metadata
    except (yaml.YAMLError, ValueError):
        return {}


def _deployed_ref_id(ref: str) -> str | None:
    """The published id a Required read under a deployed docs root names, else ``None``."""
    candidate = Path(ref).expanduser()
    for docs_root in GLOBAL_DOCS_ROOTS:
        if candidate.is_relative_to(docs_root):
            return candidate.relative_to(docs_root).as_posix().removesuffix(_MARKDOWN_SUFFIX)
    return None


def _home_ref_id(ref: str, *, current_path: Path, source: _HomeSource, domains: set[str]) -> str | None:
    """The canonical id a home Required read names. A ref resolving to no snippet names nothing here."""
    deployed_id = _deployed_ref_id(ref)
    if deployed_id is not None:
        return deployed_id
    try:
        resolved = resolve_ref_path(ref, root_path=source.classification_root, current_path=current_path)
    except DocsPublisherResolutionError:
        return None
    if resolved is None:
        return None
    classification, _ = derive_snippet_classification(
        resolved, project_root=source.classification_root, domains=domains
    )
    return classification.id if classification is not None else None


def _home_state(procedure_id: str, path: Path, text: str, *, source: _HomeSource, domains: set[str]) -> _ProcedureState:
    metadata = _frontmatter(text)
    required_ids: frozenset[str] = frozenset()
    if _is_overview(procedure_id):
        refs, _ = extract_required_reads(text)
        required_ids = frozenset(
            ref_id
            for ref in refs
            if (ref_id := _home_ref_id(ref, current_path=path, source=source, domains=domains)) is not None
        )
    return _ProcedureState(
        procedure_id=procedure_id,
        path=path,
        in_home=True,
        has_root_frontmatter=_has_root_frontmatter(metadata),
        role=_declared_role(metadata),
        required_ids=required_ids,
    )


def _home_sources(project_root: Path, tier_roots: Collection[Path]) -> list[_HomeSource]:
    sources = [_HomeSource(root, project_root) for root in iter_snippet_roots(project_root)]
    sources.extend(_HomeSource(tier_root / _DOCS_DIRNAME, tier_root) for tier_root in tier_roots)
    return sources


def _home_states(project_root: Path, tier_roots: Collection[Path], domains: set[str]) -> list[_ProcedureState]:
    """Every procedure state in the validated home: live files and non-empty companions."""
    states: list[_ProcedureState] = []
    for source in _home_sources(project_root, tier_roots):
        for path in sorted(snippet_files(source.snippets_root, include_baseline=False)):
            if is_retirement_companion(path):
                continue
            classification, _ = derive_snippet_classification(
                path, project_root=source.classification_root, domains=domains
            )
            if classification is None or classification.type is not SnippetTaxonomy.PROCEDURE:
                continue
            try:
                text = read_markdown(path)
            except OSError:
                continue  # per-snippet validation reports an unreadable home file
            states.append(_home_state(classification.id, path, text, source=source, domains=domains))
    return states


def _published_docs_dir() -> Path | None:
    """The docs directory holding the merged index validation grades against, else ``None``.

    The runtime home's own when it holds an index. A slug worktree's isolated home and a scratch
    grading home hold none, so the machine's default home, which the documentation roots already
    name, is read instead: the published documentation exists whichever home runs the check.
    """
    return next(
        (docs_dir for docs_dir in reversed(GLOBAL_DOCS_ROOTS) if published_index_path(docs_dir).is_file()), None
    )


def _deployed_file(entry: Mapping[str, object], docs_dir: Path) -> Path | None:
    path = entry.get(IndexKey.PATH)
    return docs_dir.parent / path if isinstance(path, str) and path else None


def _companion_files(deployed: Path) -> list[Path]:
    """The non-empty pending replacements the index leaves out beside a deployed file."""
    pattern = _COMPANION_GLOB.format(stem=glob.escape(deployed.stem))
    return sorted(
        companion
        for companion in deployed.parent.glob(pattern)
        if companion_slug(companion) is not None and companion.stat().st_size > 0
    )


def _read_deployed(path: Path) -> str | None:
    try:
        return read_markdown(path)
    except OSError as exc:
        _error(_READ_FAILED_FINDING, path=str(path), error=str(exc))
        return None


def _deployed_required_ids(text: str) -> frozenset[str]:
    refs, _ = extract_required_reads(text)
    return frozenset(ref_id for ref in refs if (ref_id := _deployed_ref_id(ref)) is not None)


def _deployed_state(procedure_id: str, path: Path, metadata: Mapping[str, object]) -> _ProcedureState:
    """A published state; Required reads are read from the deployed file for an overview only."""
    required_ids: frozenset[str] = frozenset()
    if _is_overview(procedure_id):
        text = _read_deployed(path)
        required_ids = _deployed_required_ids(text) if text is not None else frozenset()
    return _ProcedureState(
        procedure_id=procedure_id,
        path=path,
        in_home=False,
        has_root_frontmatter=_has_root_frontmatter(metadata),
        role=_declared_role(metadata),
        required_ids=required_ids,
    )


def _entry_states(procedure_id: str, entry: Mapping[str, object], docs_dir: Path) -> list[_ProcedureState]:
    """The live state from the index row, and each pending companion's from its deployed file."""
    deployed = _deployed_file(entry, docs_dir)
    live_path = deployed if deployed is not None else docs_dir / f"{procedure_id}{_MARKDOWN_SUFFIX}"
    states = [_deployed_state(procedure_id, live_path, entry)]
    if deployed is None or not entry.get(IndexKey.SUPERSEDED_BY):
        return states
    for companion in _companion_files(deployed):
        text = _read_deployed(companion)
        if text is not None:
            states.append(_deployed_state(procedure_id, companion, _frontmatter(text)))
    return states


def _own_sources(project_root: Path, tier_roots: Collection[Path]) -> frozenset[str]:
    """The ``source_project`` tokens whose published entries the validated home itself supplies."""
    tokens = {project_slug(project_root)}
    for tier_root in tier_roots:
        scope = tier_root_kind(tier_root)
        if scope is not None:
            tokens.add(tier_source_project(scope, tier_root.expanduser().resolve().name))
    return frozenset(tokens)


def _published_states(
    project_root: Path, tier_roots: Collection[Path], home_ids: Collection[str]
) -> list[_ProcedureState]:
    """Every procedure state the published documentation holds that the home does not supply itself.

    No index in any documentation root is no published view. An index that exists and cannot be
    read is a finding, because an empty view would hide collisions.
    """
    docs_dir = _published_docs_dir()
    if docs_dir is None:
        return []
    try:
        entries = read_published_snippets(docs_dir)
    except (OSError, yaml.YAMLError, ValueError) as exc:
        _error(
            CompositionFinding.PUBLISHED_INDEX_UNREADABLE.value,
            path=str(published_index_path(docs_dir)),
            error=str(exc),
        )
        return []
    own_sources = _own_sources(project_root, tier_roots)
    states: list[_ProcedureState] = []
    for entry in entries:
        procedure_id = entry.get(IndexKey.ID)
        if entry.get(IndexKey.TYPE) != SnippetTaxonomy.PROCEDURE or not isinstance(procedure_id, str):
            continue
        if entry.get(IndexKey.SOURCE_PROJECT) in own_sources or procedure_id in home_ids:
            continue
        states.extend(_entry_states(procedure_id, entry, docs_dir))
    return states


def _by_id(states: Iterable[_ProcedureState]) -> Corpus:
    grouped: defaultdict[str, list[_ProcedureState]] = defaultdict(list)
    for state in states:
        grouped[state.procedure_id].append(state)
    return {procedure_id: tuple(group) for procedure_id, group in grouped.items()}


def _finding_path(corpus: Corpus, ids: Collection[str], scoped_ids: frozenset[str] | None) -> Path:
    """A file the committer can open: a scoped procedure's home source first, else any home source."""
    ordered = sorted(ids, key=lambda procedure_id: (scoped_ids is None or procedure_id not in scoped_ids, procedure_id))
    states = [state for procedure_id in ordered for state in corpus[procedure_id]]
    return next((state.path for state in states if state.in_home), states[0].path)


def _report(
    code: CompositionFinding,
    ids: Collection[str],
    *,
    corpus: Corpus,
    scoped_ids: frozenset[str] | None,
    **fields: str,
) -> None:
    """Report a finding on a full run, or on a scoped run only when a scoped procedure is involved."""
    if scoped_ids is not None and scoped_ids.isdisjoint(ids):
        return
    _error(code.value, path=str(_finding_path(corpus, ids, scoped_ids)), **fields)


def _check_shared_roles(corpus: Corpus, scoped_ids: frozenset[str] | None) -> None:
    ids_by_role: defaultdict[str, set[str]] = defaultdict(set)
    for procedure_id, states in corpus.items():
        for state in states:
            if state.role is not None:
                ids_by_role[state.role].add(procedure_id)
    for role, ids in sorted(ids_by_role.items()):
        if len(ids) > 1:
            _report(
                CompositionFinding.ROLE_SHARED,
                ids,
                corpus=corpus,
                scoped_ids=scoped_ids,
                role=role,
                procedure_ids=_LIST_SEPARATOR.join(sorted(ids)),
            )


def _check_subprocedure_reads(corpus: Corpus, scoped_ids: frozenset[str] | None) -> None:
    for overview_id, states in sorted(corpus.items()):
        entry_states = [state for state in states if state.has_root_frontmatter]
        if not _is_overview(overview_id) or not entry_states:
            continue
        required_ids = frozenset().union(*(state.required_ids for state in entry_states))
        for required_id in sorted(required_ids):
            if required_id == overview_id or _group_folder(required_id) != _group_folder(overview_id):
                continue
            if any(not state.has_root_frontmatter for state in corpus.get(required_id, ())):
                _report(
                    CompositionFinding.SUBPROCEDURE_REQUIRED,
                    (overview_id, required_id),
                    corpus=corpus,
                    scoped_ids=scoped_ids,
                    overview_id=overview_id,
                    procedure_id=required_id,
                )


def _scoped_procedure_ids(home: Iterable[_ProcedureState], scoped_paths: Iterable[Path]) -> frozenset[str]:
    scoped = {path.resolve() for path in scoped_paths}
    return frozenset(state.procedure_id for state in home if state.path.resolve() in scoped)


def validate_procedure_composition(
    project_root: Path,
    *,
    tier_roots: Collection[Path],
    domains: set[str],
    scoped_paths: Collection[Path] | None,
) -> None:
    """Hold procedure composition across the validated home and the published documentation.

    ``scoped_paths`` is ``None`` on a full run, which reports every finding. On a scoped run the pass
    runs only when a scoped path is a home procedure file, and reports only findings that involve
    such a procedure: a collision is seen at the commit that introduces it, and a commit touching
    other files is not blocked by a violation it did not cause.
    """
    home = _home_states(project_root, tier_roots, domains)
    scoped_ids = None if scoped_paths is None else _scoped_procedure_ids(home, scoped_paths)
    if scoped_ids is not None and not scoped_ids:
        return
    published = _published_states(project_root, tier_roots, {state.procedure_id for state in home})
    corpus = _by_id([*home, *published])
    _check_shared_roles(corpus, scoped_ids)
    _check_subprocedure_reads(corpus, scoped_ids)
