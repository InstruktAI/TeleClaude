"""Context selector for agent injection and tool schema resolution."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import frontmatter
import yaml
from instrukt_ai_logging import get_logger

from teleclaude.caller_identity import CliCaller, DocsTier, PersonCliCaller, RoleResolver, SystemCliCaller
from teleclaude.config.schema import AppConfig, ConfigKind
from teleclaude.constants import HUMAN_ROLE_ADMIN, SNIPPET_VISIBILITY_INTERNAL, TAXONOMY_TYPES
from teleclaude.core.organization import OrganizationalMembership, resolve_organization
from teleclaude.doc_body import (
    INLINE_REF_RE,
    apply_planned_change_sections,
    apply_planned_sections,
    resolve_inline_refs,
    split_frontmatter,
)
from teleclaude.docs_index import extract_required_reads, get_project_slug
from teleclaude.docs_publishers import (
    DocsPublisherResolutionError,
    resolve_global_doc_source,
)
from teleclaude.domains import publishes_for_root, valid_domains
from teleclaude.paths import COMPANIES_ROOT, GLOBAL_DOCS_DIR, REPO_ROOT, TELECLAUDE_HOME
from teleclaude.required_reads import strip_required_reads_section
from teleclaude.services.project_catalog import get_project_catalog_service
from teleclaude.slug import normalize_slug
from teleclaude.snippet_roots import iter_tier_snippet_roots
from teleclaude.snippet_scope import HOME_SCOPES, home_identity_prefix, home_scope_for_prefix
from teleclaude.snippet_validation import (
    DOCS_HALVES,
    SnippetClassification,
    SnippetScope,
    companion_slug,
    derive_snippet_classification,
    load_domains,
    tier_root_kind,
)
from teleclaude.third_party_index import ThirdPartyMeta, load_third_party_index

logger = get_logger(__name__)

SCOPE_ORDER = {"global": 0, "company": 1, "project": 2, "person": 3}
GLOBAL_SOURCE_PROJECT = "global"
ACTIVATION_CLOSURE_REQUEST_ERROR = (
    "ERROR: --closure requires exactly one requested snippet ID and no --scope, --project, or --target filter."
)
ACTIVATION_CLOSURE_ROOT_ERROR = "ERROR: --closure requires one delivered taxonomy procedure."
ACTIVATION_CLOSURE_UNREADABLE_ERROR = "ERROR: Unable to read eligible required-read snippet: {}"
_DOCS_DIRNAME = "docs"
_LOCAL_HALF = "local"
_BASELINE_MANIFEST_FILENAME = "baseline.md"
_INDEX_FILENAME = "index.yaml"
#: ``<prefix>/<slug>/<taxonomy>/<rest>`` — the shortest home-qualified identity.
_HOME_IDENTITY_MIN_SEGMENTS = 4
#: ``<domain>/<taxonomy>/<rest>`` — the shortest domain identity.
_DOMAIN_IDENTITY_MIN_SEGMENTS = 3


class DocsSelectionEvent(StrEnum):
    SELECTED = "docs_retrieval_selected"


class DocsSelectionOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    EMPTY = "empty"
    UNKNOWN = "unknown"
    DENIED = "denied"


class DocsSelectionSource(StrEnum):
    CURRENT_PROJECT = "current_project"
    LANDED_HOME = "landed_home"
    NO_HOME = "no_home"
    EXPLICIT_PROJECT = "explicit_project"


class ActivationClosureError(ValueError):
    """Raised when a requested activation closure cannot be complete."""


@dataclass(frozen=True)
class SelectionCounts:
    global_snippet_count: int
    current_project_snippet_count: int
    other_project_snippet_count: int


def _selection_counts(
    snippets: Iterable[SnippetMeta], *, current_project_slug: str | None, other_project_slugs: set[str | None]
) -> SelectionCounts:
    global_count = 0
    current_project_count = 0
    other_project_count = 0
    for snippet in snippets:
        source_project = snippet.source_project.lower()
        if source_project == GLOBAL_SOURCE_PROJECT:
            global_count += 1
        elif current_project_slug is not None and source_project == current_project_slug:
            current_project_count += 1
        elif source_project in other_project_slugs:
            other_project_count += 1
    return SelectionCounts(global_count, current_project_count, other_project_count)


def _emit_selection_summary(
    *,
    retrieval_id: str | None,
    verb: str | None,
    source_reason: DocsSelectionSource,
    selection_outcome: DocsSelectionOutcome,
    counts: SelectionCounts,
    denied_count: int,
    rendered_count: int,
    target_delivered_count: int,
    target_superseded_count: int,
    dependency_count: int,
) -> None:
    if retrieval_id is None or verb is None:
        return
    logger.info(
        DocsSelectionEvent.SELECTED.value,
        retrieval_id=retrieval_id,
        verb=verb,
        source_reason=source_reason.value,
        selection_outcome=selection_outcome.value,
        global_snippet_count=counts.global_snippet_count,
        current_project_snippet_count=counts.current_project_snippet_count,
        other_project_snippet_count=counts.other_project_snippet_count,
        denied_count=denied_count,
        rendered_count=rendered_count,
        target_delivered_count=target_delivered_count,
        target_superseded_count=target_superseded_count,
        dependency_count=dependency_count,
    )


@dataclass(frozen=True)
class SnippetMeta:
    snippet_id: str
    description: str
    snippet_type: str
    scope: str
    domain: str
    path: Path
    source_project: str = ""
    project_root: Path | None = None
    visibility: str = SNIPPET_VISIBILITY_INTERNAL
    activation_trigger: str | None = None
    delivered_by: tuple[str, ...] = ()
    superseded_by: tuple[str, ...] = ()


_UNKNOWN_SCOPE_RANK = len(SCOPE_ORDER)


def _scope_rank(scope: str | None) -> int:
    if not scope:
        return _UNKNOWN_SCOPE_RANK
    return SCOPE_ORDER.get(scope, _UNKNOWN_SCOPE_RANK)


_TEST_ENABLED_ENV = "TELECLAUDE_GET_CONTEXT_TESTING"
_index_cache: dict[str, tuple[float, list[SnippetMeta]]] = {}


def _write_test_output(
    *,
    phase: str,
    areas: list[str],
    index_ids: list[str],
    selected_ids: list[str],
    test_agent: str | None = None,
    test_mode: str | None = None,
    test_request: str | None = None,
    test_csv_path: str | None = None,
) -> None:
    if not os.getenv(_TEST_ENABLED_ENV):  # fmt: skip  # guard: direct-env-read - allowed: bootstrap or internal process signal
        return
    csv_path = test_csv_path
    agent = test_agent
    mode = test_mode
    request_text = (test_request or "").strip()
    if not csv_path or not agent or not mode or not request_text:
        return
    if mode not in {"fast", "med", "slow"}:
        return
    try:
        rows = []
        with open(csv_path, encoding="utf-8") as handle:
            header = handle.readline().strip().split(",")
            for line in handle:
                rows.append(line.strip().split(","))
    except Exception:
        return
    if not header:
        return

    def _set(row: list[str], col: str, value: str) -> None:
        if col not in header:
            return
        idx = header.index(col)
        while len(row) <= idx:
            row.append("")
        row[idx] = value

    for row in rows:
        if not row:
            continue
        if len(row) <= 2:
            continue
        if row[1] != agent:
            continue
        variants = row[2].split("|") if row[2] else []
        if request_text not in [v.strip() for v in variants]:
            continue
        if phase == "phase1":
            _set(row, f"{mode}_phase1_areas", "|".join(areas))
            _set(row, f"{mode}_phase1_index_ids", "|".join(index_ids))
        if phase == "phase2":
            _set(row, f"{mode}_phase2_selected_ids", "|".join(selected_ids))
        break

    try:
        with open(csv_path, "w", encoding="utf-8") as handle:
            handle.write(",".join(header) + "\n")
            for row in rows:
                handle.write(",".join(row) + "\n")
    except Exception:
        return


def _load_baseline_ids(
    baseline_path: Path,
    snippets_by_path: dict[str, SnippetMeta],
    *,
    project_root: Path,
    required: bool = False,
) -> set[str]:
    """Load baseline manifest and return referenced snippet IDs.

    Args:
        baseline_path: Path to baseline.md manifest file
        snippets_by_path: Mapping of resolved paths to snippets
        project_root: Project root for resolving relative paths
        required: When True, the manifest is part of a contract invariant
            (e.g. a published domain's deployed ``<domain>/baseline.md`` that
            exists). Absence or read failure raises rather than degrading to an
            empty set, so silent context drop becomes a hard error.

    Returns:
        Set of snippet IDs referenced in the baseline manifest
    """
    if not baseline_path.exists():
        if required:
            raise FileNotFoundError(f"Required baseline manifest missing: {baseline_path}")
        return set()

    if required:
        # Let OSError propagate — contract violation, not optional condition.
        content = baseline_path.read_text(encoding="utf-8")
    else:
        try:
            content = baseline_path.read_text(encoding="utf-8")
        except Exception:
            return set()

    baseline_ids: set[str] = set()
    for match in INLINE_REF_RE.finditer(content):
        ref = match.group(1)
        candidate = Path(ref).expanduser()
        if not candidate.is_absolute():
            candidate = (project_root / candidate).resolve()
        else:
            candidate = candidate.resolve()
        snippet = snippets_by_path.get(str(candidate))
        if snippet:
            baseline_ids.add(snippet.snippet_id)

    return baseline_ids


def _resolve_requires(
    selected_ids: Iterable[str],
    snippets: list[SnippetMeta],
) -> list[SnippetMeta]:
    snippets_by_id = {s.snippet_id: s for s in snippets}
    snippets_by_path = {str(s.path): s for s in snippets}

    resolved: list[SnippetMeta] = []
    seen: set[str] = set()
    stack: list[SnippetMeta] = []

    for sid in selected_ids:
        snippet = snippets_by_id.get(sid)
        if snippet:
            stack.append(snippet)

    while stack:
        current = stack.pop()
        if str(current.path) in seen:
            continue
        seen.add(str(current.path))
        resolved.append(current)
        # Read @ refs from the snippet file's Required reads section
        try:
            content = current.path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("resolve_requires_read_failed", path=str(current.path), error=str(exc))
            continue
        ref_paths = extract_required_reads(content)
        for ref in ref_paths:
            ref_resolved = Path(ref).expanduser().resolve()
            req_snippet = snippets_by_path.get(str(ref_resolved))
            if not req_snippet and not Path(ref).is_absolute():
                req_snippet = snippets_by_path.get(str((current.path.parent / ref).resolve()))
            if not req_snippet or str(req_snippet.path) in seen:
                continue
            same_project = req_snippet.source_project == current.source_project
            if not same_project and req_snippet.scope != "global":
                continue
            if req_snippet:
                stack.append(req_snippet)

    resolved.sort(key=lambda s: (TAXONOMY_TYPES.index(s.snippet_type), _scope_rank(s.scope), s.snippet_id))
    return resolved


def _build_project_catalog_output() -> str:
    catalog_nodes = sorted(
        get_project_catalog_service().list_projects(),
        key=lambda node: node.slug,
    )
    parts = [
        "# PHASE 0: Project Catalog",
        "# Available projects registered in ~/.teleclaude/projects.yaml",
        "",
    ]
    if not catalog_nodes:
        parts.append("No registered projects found.")
    else:
        for node in catalog_nodes:
            description = (node.config.description or "").strip() or "(no description)"
            parts.append(f"{node.slug}: {description}")
    parts.extend(
        [
            "",
            "# ⚠️  IMPORTANT: Call telec docs again to browse snippet indexes for the project(s) you need.",
        ]
    )
    return "\n".join(parts)


class TierDepth(StrEnum):
    """How much of an assembled tier's material a caller may read."""

    FULL = "full"
    PUBLIC_ONLY = "public_only"


@dataclass(frozen=True)
class TierKey:
    """One assembled tier: its scope and, for a qualified tier, its owner slug.

    ``owner`` is ``None`` for the global tier, which has no owner segment.
    """

    scope: SnippetScope
    owner: str | None = None


@dataclass(frozen=True)
class HomeCatalog:
    """One documentation home: its tier key, root, and the local catalog served in place."""

    tier: TierKey
    root: Path

    @property
    def local_index(self) -> Path:
        """The home's local catalog, ``docs/local/index.yaml``."""
        return self.root / _DOCS_DIRNAME / _LOCAL_HALF / _INDEX_FILENAME

    @property
    def source_project(self) -> str:
        """The ``source_project`` value its snippets carry: the slug, or ``<kind>:<slug>`` for a tier."""
        if self.tier.scope is SnippetScope.PROJECT:
            return self.tier.owner or ""
        return f"{self.tier.scope.value}:{self.tier.owner}"


class HomeResolver:
    """Map ``(kind, slug)`` to a home: projects from the registry, people and companies from the platform home.

    Slugs are looked up among declared homes and never joined into a path. The
    home an invocation landed in is served from the landed root itself, whether
    or not it is registered.
    """

    def __init__(self, platform_home: Path = TELECLAUDE_HOME, *, landed: HomeCatalog | None = None) -> None:
        self._platform_home = platform_home
        self._landed = landed
        self._homes: dict[TierKey, HomeCatalog] | None = None

    def _load(self) -> dict[TierKey, HomeCatalog]:
        homes: dict[TierKey, HomeCatalog] = {}
        for node in get_project_catalog_service().list_projects():
            key = TierKey(SnippetScope.PROJECT, node.slug)
            homes[key] = HomeCatalog(key, node.root.expanduser().resolve())
        for root, kind in iter_tier_snippet_roots(self._platform_home):
            scope = SnippetScope.COMPANY if kind is ConfigKind.COMPANY else SnippetScope.PERSON
            key = TierKey(scope, root.name)
            homes[key] = HomeCatalog(key, root.expanduser().resolve())
        return homes

    def resolve(self, tier: TierKey) -> HomeCatalog | None:
        """Return the declared home for ``tier``, or ``None`` when no such home exists."""
        if tier.scope is SnippetScope.GLOBAL or tier.owner is None:
            return None
        if self._landed is not None and self._landed.tier == tier:
            return self._landed
        if self._homes is None:
            self._homes = self._load()
        return self._homes.get(tier)


def home_tier_for_snippet_id(snippet_id: str) -> TierKey | None:
    """Parse the owning home from a qualified identity (``projects|people|companies/<slug>/…``)."""
    segments = snippet_id.strip().split("/")
    if len(segments) < _HOME_IDENTITY_MIN_SEGMENTS or not segments[1]:
        return None
    scope = home_scope_for_prefix(segments[0])
    if scope is None:
        return None
    return TierKey(scope, segments[1])


def _load_index(
    index_path: Path,
    *,
    source_project: str = "",
    project_root: Path | None = None,
) -> list[SnippetMeta]:
    resolved_index = index_path.expanduser().resolve()
    if not resolved_index.exists():
        logger.warning("snippet_index_missing", path=str(resolved_index))
        return []

    try:
        mtime = resolved_index.stat().st_mtime
    except OSError:
        logger.warning("snippet_index_stat_failed", path=str(resolved_index))
        return []

    cache_key = str(resolved_index)
    cached = _index_cache.get(cache_key)
    if cached and cached[0] == mtime:
        base_entries = cached[1]
    else:
        try:
            payload = yaml.safe_load(resolved_index.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.exception("snippet_index_load_failed", path=str(resolved_index), error=str(exc))
            return []

        if not isinstance(payload, dict):
            return []

        payload_root = payload.get("project_root")
        snippets = payload.get("snippets")
        if not isinstance(payload_root, str) or not isinstance(snippets, list):
            return []

        root_path = Path(payload_root).expanduser().resolve()
        loaded_entries: list[SnippetMeta] = []
        for item in snippets:
            if not isinstance(item, dict):
                continue
            snippet_id = item.get("id")
            description = item.get("description")
            snippet_type = item.get("type")
            scope = item.get("scope")
            domain = item.get("domain")
            raw_path = item.get("path")
            if (
                not isinstance(snippet_id, str)
                or not isinstance(description, str)
                or not isinstance(snippet_type, str)
                or not isinstance(scope, str)
                or not isinstance(domain, str)
                or not isinstance(raw_path, str)
            ):
                continue
            path = Path(raw_path).expanduser()
            if not path.is_absolute():
                path = (root_path / path).resolve()
            raw_visibility = item.get("visibility")
            visibility = raw_visibility if isinstance(raw_visibility, str) else SNIPPET_VISIBILITY_INTERNAL
            raw_activation_trigger = item.get("activation_trigger")
            activation_trigger = raw_activation_trigger if isinstance(raw_activation_trigger, str) else None
            raw_source_project = item.get("source_project")
            raw_delivered_by = item.get("delivered_by")
            delivered_by = (
                tuple(raw_delivered_by)
                if isinstance(raw_delivered_by, list) and all(isinstance(slug, str) for slug in raw_delivered_by)
                else ()
            )
            raw_superseded_by = item.get("superseded_by")
            superseded_by = (
                tuple(raw_superseded_by)
                if isinstance(raw_superseded_by, list) and all(isinstance(slug, str) for slug in raw_superseded_by)
                else ()
            )
            loaded_entries.append(
                SnippetMeta(
                    snippet_id=snippet_id,
                    description=description,
                    snippet_type=snippet_type,
                    scope=scope,
                    domain=domain,
                    path=path,
                    source_project=raw_source_project if isinstance(raw_source_project, str) else "",
                    project_root=root_path,
                    visibility=visibility,
                    activation_trigger=activation_trigger,
                    delivered_by=delivered_by,
                    superseded_by=superseded_by,
                )
            )
        _index_cache[cache_key] = (mtime, loaded_entries)
        base_entries = loaded_entries

    entries: list[SnippetMeta] = []
    for snippet in base_entries:
        entries.append(
            SnippetMeta(
                snippet_id=snippet.snippet_id,
                description=snippet.description,
                snippet_type=snippet.snippet_type,
                scope=snippet.scope,
                domain=snippet.domain,
                path=snippet.path,
                source_project=source_project or snippet.source_project,
                project_root=project_root or snippet.project_root,
                visibility=snippet.visibility or SNIPPET_VISIBILITY_INTERNAL,
                activation_trigger=snippet.activation_trigger,
                delivered_by=snippet.delivered_by,
                superseded_by=snippet.superseded_by,
            )
        )

    return entries


def _load_home_local(home: HomeCatalog) -> list[SnippetMeta]:
    """Load a home's local catalog, served in place from the home's own files."""
    return _load_index(home.local_index, source_project=home.source_project, project_root=home.root)


def resolve_caller_read_depth(
    caller: CliCaller | None,
    tier: TierKey,
    *,
    organization: OrganizationalMembership | None = None,
    role_resolver: RoleResolver | None = None,
) -> TierDepth:
    """Answer the depth ``caller`` reads ``tier`` at — full or public-only.

    An administrator at the global documentation scope and a system principal read every tier at full,
    preserving the live UC-DSP31 contract for the system caller. Otherwise
    depth follows the caller's own declared relationship to the named tier:
    their own person tier, a company they belong to, or a project they reach
    (an explicit assignment or their company's administrative coverage). A
    caller with no resolvable identity, or a relationship-holding caller with
    no relationship to the named tier, reads it at public-only.

    ``organization`` lets a caller resolving several tiers reuse one
    ``resolve_organization`` call; when omitted it is resolved from the
    caller's person slug on demand. This function recomputes nothing from a
    role — it consumes ``resolve_organization``'s answer as-is, including its
    exclusion of stale assignments from ``assignments``.
    """
    if isinstance(caller, SystemCliCaller):
        return TierDepth.FULL
    if not isinstance(caller, PersonCliCaller) or not caller.person_slug:
        return TierDepth.PUBLIC_ONLY
    resolver = role_resolver or RoleResolver()
    if resolver.role_for(caller, DocsTier(tier.scope, tier.owner)) == HUMAN_ROLE_ADMIN:
        return TierDepth.FULL
    if tier.scope is SnippetScope.GLOBAL:
        return TierDepth.PUBLIC_ONLY
    if tier.scope is SnippetScope.PERSON:
        return TierDepth.FULL if tier.owner == caller.person_slug else TierDepth.PUBLIC_ONLY
    membership = organization if organization is not None else resolve_organization(caller.person_slug)
    if tier.scope is SnippetScope.COMPANY:
        if any(entry.company_slug == tier.owner for entry in membership.memberships):
            return TierDepth.FULL
        return TierDepth.PUBLIC_ONLY
    if tier.scope is SnippetScope.PROJECT:
        reached = {ref.project_slug for ref in (*membership.assignments, *membership.covered)}
        return TierDepth.FULL if tier.owner in reached else TierDepth.PUBLIC_ONLY
    return TierDepth.PUBLIC_ONLY


def resolve_default_read_set(
    caller: CliCaller | None,
    *,
    landed_home: TierKey | None,
    current_project_company: str | None,
    role_resolver: RoleResolver | None = None,
) -> dict[TierKey, TierDepth]:
    """Answer the tiers assembled when no tier is named, each paired with its depth.

    The default read set is the caller's own person tier, every company they
    belong to, global, and what the invocation offers — the home it lands in (a
    project or a person, company or platform home) and the company a landed
    project declares as its owner — the last two at whatever depth the
    relationship grants. A caller with no resolvable identity contributes no
    relationship-derived tier; what the invocation offers still enters the set,
    read at public-only. Landing in no home offers nothing of its own.
    """
    keys: list[TierKey] = [TierKey(SnippetScope.GLOBAL)]
    organization: OrganizationalMembership | None = None
    if isinstance(caller, PersonCliCaller) and caller.person_slug:
        keys.append(TierKey(SnippetScope.PERSON, caller.person_slug))
        organization = resolve_organization(caller.person_slug)
        keys.extend(TierKey(SnippetScope.COMPANY, membership.company_slug) for membership in organization.memberships)
    if landed_home is not None:
        keys.append(landed_home)
    if current_project_company is not None:
        keys.append(TierKey(SnippetScope.COMPANY, current_project_company))
    resolver = role_resolver or RoleResolver()
    return {
        key: resolve_caller_read_depth(caller, key, organization=organization, role_resolver=resolver) for key in keys
    }


#: Scopes whose snippets belong to one home and are gated by that home's depth.
_HOME_SCOPE_VALUES = frozenset(scope.value for scope in HOME_SCOPES)


def _tier_key_for_snippet(snippet: SnippetMeta) -> TierKey:
    """Read a snippet's tier key from its own qualified identity, not the index it arrived through."""
    scope = SnippetScope(snippet.scope)
    if scope not in HOME_SCOPES:
        return TierKey(scope)
    home = home_tier_for_snippet_id(snippet.snippet_id)
    return home if home is not None else TierKey(scope)


def _include_snippet_factory(
    *,
    caller: CliCaller | None,
    read_set: Mapping[TierKey, TierDepth],
    role_resolver: RoleResolver,
) -> Callable[[SnippetMeta], bool]:
    """Gate each assembled snippet by depth: one tier gate for every home, the global gate otherwise.

    Reach was decided at assembly; this predicate decides only how much of an
    assembled home is read. The half a snippet lives in never enters the gate.
    """
    global_depth = resolve_caller_read_depth(
        caller,
        TierKey(SnippetScope.GLOBAL),
        role_resolver=role_resolver,
    )
    global_full = isinstance(caller, SystemCliCaller) or global_depth is TierDepth.FULL

    def _include(snippet: SnippetMeta) -> bool:
        if snippet.scope in _HOME_SCOPE_VALUES:
            tier = _tier_key_for_snippet(snippet)
            depth = read_set.get(tier)
            if depth is None:
                depth = resolve_caller_read_depth(caller, tier, role_resolver=role_resolver)
            return depth is TierDepth.FULL or snippet.visibility == "public"
        return global_full or snippet.visibility == "public"

    return _include


def _apply_baseline_filter(
    snippets: list[SnippetMeta],
    *,
    baseline_only: bool,
    global_root: Path,
    snippets_by_path: dict[str, SnippetMeta],
    project_roots: set[Path],
) -> list[SnippetMeta]:
    if not baseline_only:
        return snippets
    baseline_ids: set[str] = set()
    # The baseline is the union of every published domain's manifest, read from
    # the deployed corpus, which carries each domain's tree whole. A domain
    # without a manifest contributes nothing; an existing manifest that cannot
    # be read fails the selection.
    for domain in sorted(valid_domains()):
        domain_manifest = global_root / domain / _BASELINE_MANIFEST_FILENAME
        if not domain_manifest.exists():
            continue
        baseline_ids.update(
            _load_baseline_ids(domain_manifest, snippets_by_path, project_root=global_root, required=True)
        )
    for project_root in project_roots:
        baseline_ids.update(
            _load_baseline_ids(
                project_root / _DOCS_DIRNAME / _LOCAL_HALF / _BASELINE_MANIFEST_FILENAME,
                snippets_by_path,
                project_root=project_root,
            )
        )
    return [snippet for snippet in snippets if snippet.snippet_id in baseline_ids]


def _tier_read_set_lines(read_set: Mapping[TierKey, TierDepth], snippets: Iterable[SnippetMeta]) -> list[str]:
    """Render one line per person/company tier in the caller's read set, with its entry count.

    An empty participating tier is named with a zero count, so a reader can
    distinguish it from a tier that does not exist; a tier outside the read
    set is not named at all.
    """
    tier_keys = [key for key in read_set if key.scope in (SnippetScope.PERSON, SnippetScope.COMPANY)]
    if not tier_keys:
        return []
    counts: dict[TierKey, int] = dict.fromkeys(tier_keys, 0)
    for snippet in snippets:
        if snippet.scope not in _HOME_SCOPE_VALUES:
            continue
        key = _tier_key_for_snippet(snippet)
        if key in counts:
            counts[key] += 1
    ordered_keys = sorted(tier_keys, key=lambda key: (key.scope.value, key.owner or ""))
    return [f"# Tier {home_identity_prefix(key.scope)}/{key.owner}: {counts[key]} snippet(s)" for key in ordered_keys]


def _build_phase1_output(
    snippets_for_selection: list[SnippetMeta],
    third_party_entries: list[ThirdPartyMeta],
    *,
    areas: list[str],
    read_set: Mapping[TierKey, TierDepth],
    test_agent: str | None,
    test_mode: str | None,
    test_request: str | None,
    test_csv_path: str | None,
) -> str:
    parts = [
        "# PHASE 1: Snippet Index (IDs + descriptions)",
        "# Review the snippets below and select the IDs you need.",
        f"# Filter with --areas <{'|'.join(TAXONOMY_TYPES)}> and/or --domains <{'|'.join(sorted(valid_domains()))}> (omit for all)",
        *_tier_read_set_lines(read_set, snippets_for_selection),
        "",
    ]
    ordered = sorted(
        snippets_for_selection,
        key=lambda s: (TAXONOMY_TYPES.index(s.snippet_type), _scope_rank(s.scope), s.snippet_id),
    )
    _write_test_output(
        phase="phase1",
        areas=areas,
        index_ids=[snippet.snippet_id for snippet in ordered],
        selected_ids=[],
        test_agent=test_agent,
        test_mode=test_mode,
        test_request=test_request,
        test_csv_path=test_csv_path,
    )
    for snippet in ordered:
        line = f"{snippet.snippet_id}: {snippet.description or ''}".strip()
        if snippet.delivered_by:
            line += f"  (delivered by: {', '.join(snippet.delivered_by)})"
        if snippet.superseded_by:
            line += f"  (superseded by: {', '.join(snippet.superseded_by)})"
        parts.append(line)
    if third_party_entries:
        parts.append("")
        parts.append("# Third-party documentation (not part of taxonomy)")
        for entry in sorted(third_party_entries, key=lambda s: (_scope_rank(s.scope), s.snippet_id)):
            parts.append(f"{entry.snippet_id}: {entry.description or ''}".strip())
    parts.extend(["", "# ⚠️  IMPORTANT: Call `telec docs get` again with the snippet IDs of interest!"])
    parts.extend(
        [
            "",
            "# NOTE: Pending work is flagged inline, never hidden: `(delivered by: slug)` marks a",
            "# not-yet-live NEW snippet; `(superseded by: slug)` marks a LIVE snippet with an incoming",
            "# rework (companion file or planned section). The bodies stay invisible until active —",
            "# `telec docs get` strips planned sections; `telec docs get <id> --target <slug>` reveals them.",
            "# `telec docs index --target <slug>` focuses on one todo's new snippets.",
        ]
    )
    return "\n".join(parts)


def _partition_selected_ids(
    snippet_ids: list[str] | None,
    valid_ids: set[str],
    all_loaded_ids: set[str],
    third_party_by_id: dict[str, ThirdPartyMeta],
) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
    selected_ids = list(snippet_ids or [])
    denied_ids = [sid for sid in selected_ids if sid not in valid_ids and sid in all_loaded_ids]
    unknown_ids = [sid for sid in selected_ids if sid not in valid_ids and sid not in all_loaded_ids]
    allowed_ids = [sid for sid in selected_ids if sid not in denied_ids]
    taxonomy_ids = [sid for sid in allowed_ids if sid not in third_party_by_id]
    third_party_ids = [sid for sid in allowed_ids if sid in third_party_by_id]
    return selected_ids, denied_ids, unknown_ids, taxonomy_ids, third_party_ids


def _read_selected_snippet_body(
    snippet: SnippetMeta,
    *,
    project_root: Path,
    global_root: Path,
    global_snippets_root: Path,
    target_slug: str | None,
) -> str | None:
    if snippet.delivered_by and target_slug not in snippet.delivered_by:
        return None
    try:
        source_path = _target_body_source_path(snippet.path, target_slug)
        raw = source_path.read_text(encoding="utf-8")
        root_path = (
            global_root if global_snippets_root in snippet.path.parents else (snippet.project_root or project_root)
        )
        content = resolve_inline_refs(raw, snippet_path=source_path, root_path=root_path)
        _, body = split_frontmatter(content)
        body = apply_planned_change_sections(body, target_slug)
        body = apply_planned_sections(body, target_slug)
        return strip_required_reads_section(body)
    except Exception as exc:
        logger.exception("context_selector_read_failed", path=str(snippet.path), error=str(exc))
        return None


def _target_body_source_path(snippet_path: Path, target_slug: str | None) -> Path:
    if target_slug is None:
        return snippet_path
    companion_path = snippet_path.with_name(f"{snippet_path.stem}.{target_slug}.md")
    if companion_path.exists() and companion_slug(companion_path) == target_slug:
        return companion_path
    return snippet_path


def _pending_changes_awareness_lines(snippet: SnippetMeta) -> list[str]:
    slugs = ", ".join(snippet.superseded_by)
    related_glob = snippet.path.with_suffix("").name + ".*"
    return [
        "",
        "# NOTE: This snippet has pending changes.",
        f"# Owners: {slugs}",
        "# The text above is the current contract. The on-disk file carries in-flight markers",
        "# and/or a companion; before editing, run the related-files discovery",
        f"# (`ls {related_glob}`) and read `telec docs get {snippet.snippet_id} --target <slug>`.",
    ]


def _validate_activation_closure_request(
    *,
    snippet_ids: list[str] | None,
    scope: SnippetScope | None,
    projects: list[str] | None,
    target_slug: str | None,
    root: SnippetMeta | None = None,
    validate_root: bool = False,
) -> None:
    """Reject closure requests that cannot truthfully claim a complete activation context."""
    if len(snippet_ids or []) != 1 or scope is not None or projects or target_slug is not None:
        raise ActivationClosureError(ACTIVATION_CLOSURE_REQUEST_ERROR)
    if not validate_root:
        return
    if root is None or root.snippet_type != "procedure" or root.delivered_by:
        raise ActivationClosureError(ACTIVATION_CLOSURE_ROOT_ERROR)


def _owning_project_root(resolved_path: Path, *, relative_tail: Path) -> Path:
    """Recover a publisher's project root from a resolved global-doc source path.

    ``resolve_global_doc_source`` returns ``owner.docs_global / relative_tail``;
    stripping the tail and the trailing ``docs/global`` pair yields the same
    root ``docs_global.parent.parent`` derives elsewhere (``docs_publishers.py``).
    """
    ancestor_parts = len(relative_tail.parts) + 2
    return Path(*resolved_path.parts[:-ancestor_parts])


def _snippet_meta_from_file(
    snippet_id: str,
    path: Path,
    *,
    classification: SnippetClassification,
    project_root: Path,
    source_project: str,
) -> SnippetMeta:
    post = frontmatter.load(str(path))
    metadata: Mapping[str, object] = post.metadata or {}
    description = metadata.get("description")
    activation_trigger = metadata.get("activation_trigger")
    raw_visibility = metadata.get("visibility")
    raw_delivered_by = metadata.get("delivered_by")
    delivered_by = (
        tuple(raw_delivered_by)
        if isinstance(raw_delivered_by, list) and all(isinstance(slug, str) for slug in raw_delivered_by)
        else ()
    )
    return SnippetMeta(
        snippet_id=snippet_id,
        description=description if isinstance(description, str) else "",
        snippet_type=classification.type.value,
        scope=classification.scope.value,
        domain=classification.domain,
        path=path,
        source_project=source_project,
        project_root=project_root,
        visibility=raw_visibility if isinstance(raw_visibility, str) else SNIPPET_VISIBILITY_INTERNAL,
        activation_trigger=activation_trigger if isinstance(activation_trigger, str) else None,
        delivered_by=delivered_by,
    )


def _resolve_home_scope_meta(requested: str, taxonomy: str, rest: str, *, home: HomeCatalog) -> SnippetMeta | None:
    """Resolve a home-qualified identity from whichever half of that home holds it.

    A project's local half is its only home half; a person or company home
    serves both halves under one identity.
    """
    halves = (_LOCAL_HALF,) if home.tier.scope is SnippetScope.PROJECT else DOCS_HALVES
    for half in halves:
        candidate = home.root / _DOCS_DIRNAME / half / taxonomy / f"{rest}.md"
        if not candidate.is_file():
            continue
        classification, _ = derive_snippet_classification(
            candidate, project_root=home.root, domains=load_domains(home.root)
        )
        if classification is None or classification.id != requested:
            continue
        return _snippet_meta_from_file(
            requested,
            candidate,
            classification=classification,
            project_root=home.root,
            source_project=home.source_project,
        )
    return None


def _resolve_global_scope_meta(
    requested: str,
    scope_segment: str,
    taxonomy: str,
    rest: str,
    *,
    project_root: Path,
) -> SnippetMeta | None:
    candidate = GLOBAL_DOCS_DIR / scope_segment / taxonomy / f"{rest}.md"
    relative_tail = candidate.relative_to(GLOBAL_DOCS_DIR)
    try:
        resolved = resolve_global_doc_source(project_root, candidate)
    except DocsPublisherResolutionError:
        return None
    if resolved == candidate or not resolved.is_file():
        return None
    owner_root = _owning_project_root(resolved, relative_tail=relative_tail)
    classification, _ = derive_snippet_classification(
        resolved, project_root=owner_root, domains=load_domains(owner_root)
    )
    if classification is None:
        return None
    return _snippet_meta_from_file(
        requested,
        resolved,
        classification=classification,
        project_root=owner_root,
        source_project=GLOBAL_SOURCE_PROJECT,
    )


def resolve_snippet_meta(
    snippet_id: str, *, project_root: Path, home_resolver: HomeResolver | None = None
) -> SnippetMeta | None:
    """Resolve one taxonomy snippet ID from its publisher or home source tree.

    A home-qualified identity (``projects|people|companies/<slug>/…``) resolves
    against that home's files wherever the caller runs; a domain identity
    resolves against its publisher's source — never the deployed index — so
    resolution never depends on a documentation deployment having run yet. An
    owner that names no declared home resolves to nothing. Third-party IDs are
    outside the taxonomy and never resolve here.
    """
    requested = snippet_id.strip()
    if not requested:
        return None
    home_tier = home_tier_for_snippet_id(requested)
    if home_tier is not None:
        segments = requested.split("/")
        taxonomy, rest_parts = segments[2], segments[3:]
        if not rest_parts or not all(rest_parts):
            return None
        home = (home_resolver or HomeResolver()).resolve(home_tier)
        if home is None:
            return None
        return _resolve_home_scope_meta(requested, taxonomy, "/".join(rest_parts), home=home)
    segments = requested.split("/")
    if len(segments) < _DOMAIN_IDENTITY_MIN_SEGMENTS:
        return None
    scope_segment, taxonomy, *rest_parts = segments
    if not taxonomy or not rest_parts or not all(rest_parts):
        return None
    if home_scope_for_prefix(scope_segment) is not None:
        return None
    return _resolve_global_scope_meta(
        requested, scope_segment, taxonomy, "/".join(rest_parts), project_root=project_root
    )


def _render_phase2_taxonomy_bodies(
    *,
    resolved: list[SnippetMeta],
    requested_set: set[str],
    closure_root: SnippetMeta | None,
    project_root: Path,
    global_root: Path,
    global_snippets_root: Path,
    target_slug: str | None,
) -> tuple[list[str], int, list[str]]:
    """Render selected snippets, or a validated activation closure, before assembling phase-two headers."""
    rendered_dependency_ids: list[str] = []
    body_parts: list[str] = []
    rendered_count = 0
    for snippet in resolved:
        if closure_root is None and snippet.snippet_id not in requested_set:
            continue
        if closure_root is not None and snippet.snippet_id != closure_root.snippet_id and snippet.delivered_by:
            continue
        body = _read_selected_snippet_body(
            snippet,
            project_root=project_root,
            global_root=global_root,
            global_snippets_root=global_snippets_root,
            target_slug=target_slug,
        )
        if body is None:
            if closure_root is not None:
                raise ActivationClosureError(ACTIVATION_CLOSURE_UNREADABLE_ERROR.format(snippet.snippet_id))
            continue
        body_parts.append(
            "\n".join(
                [
                    "---",
                    f"id: {snippet.snippet_id}",
                    f"type: {snippet.snippet_type}",
                    f"domain: {snippet.domain}",
                    f"scope: {snippet.scope}",
                    f"description: {snippet.description}",
                    "---",
                ]
            ).strip()
        )
        body_parts.append(body.lstrip("\n"))
        rendered_count += 1
        if closure_root is not None and snippet.snippet_id != closure_root.snippet_id:
            rendered_dependency_ids.append(snippet.snippet_id)
        if snippet.superseded_by and target_slug is None:
            body_parts.extend(_pending_changes_awareness_lines(snippet))
    return body_parts, rendered_count, rendered_dependency_ids


@dataclass
class AssembledCandidates:
    """Snippet candidates loaded from every home in reach for one retrieval call."""

    snippets: list[SnippetMeta]
    snippets_by_path: dict[str, SnippetMeta]
    all_loaded_ids: set[str]
    third_party_entries: list[ThirdPartyMeta]
    current_project_slug: str | None
    reach: dict[TierKey, TierDepth]
    project_roots: set[Path]
    source_reason: DocsSelectionSource
    global_root: Path
    named: bool


@dataclass(frozen=True)
class Landing:
    """Where an invocation landed: its home's tier key, project slug and owning company."""

    home: TierKey | None
    project_slug: str | None
    project_company: str | None
    root: Path | None = None

    def catalog(self) -> HomeCatalog | None:
        """The landed home served from the landed root, or ``None`` outside any home."""
        if self.home is None or self.root is None:
            return None
        return HomeCatalog(self.home, self.root.expanduser().resolve())


def resolve_landing(project_root: Path, *, landing_kind: ConfigKind | None, config: AppConfig | None) -> Landing:
    """Answer which home an invocation landed in; the landing sets only the default read set."""
    if landing_kind is ConfigKind.PROJECT:
        if config is not None and config.project is not None:
            slug = config.project.project_slug or normalize_slug(config.project.project_name or project_root.name)
            company = config.project.company
        else:
            slug = get_project_slug(project_root)
            company = None
        return Landing(TierKey(SnippetScope.PROJECT, slug), slug, company, project_root)
    if landing_kind in (ConfigKind.PERSON, ConfigKind.COMPANY):
        tier_kind = tier_root_kind(project_root)
        if tier_kind is not None:
            return Landing(TierKey(tier_kind, project_root.expanduser().resolve().name), None, None, project_root)
    return Landing(None, None, None)


def _named_homes(
    *,
    projects: list[str] | None,
    person: str | None,
    company: str | None,
    scope: SnippetScope | None,
    landing: Landing,
) -> list[TierKey] | None:
    """Homes named by selector, or ``None`` when the default read set applies.

    ``--scope project`` without ``--project`` names the landed project; with no
    landed project it names no home, so the listing is empty.
    """
    named: list[TierKey] = []
    for name in projects or []:
        key = name.strip().lower()
        if key:
            named.append(TierKey(SnippetScope.PROJECT, key))
    if person is not None:
        named.append(TierKey(SnippetScope.PERSON, person))
    if company is not None:
        named.append(TierKey(SnippetScope.COMPANY, company))
    if scope is SnippetScope.PROJECT and not projects:
        if landing.project_slug is not None:
            named.append(TierKey(SnippetScope.PROJECT, landing.project_slug))
        return named
    return named or None


def _resolve_reach(
    *,
    landing: Landing,
    named_homes: list[TierKey] | None,
    caller: CliCaller | None,
    role_resolver: RoleResolver,
    resolver: HomeResolver,
    snippet_ids: list[str] | None,
) -> dict[TierKey, TierDepth]:
    """Answer which homes are assembled and at what depth.

    Reach is the default read set, or the named homes instead of it; a home
    named by a requested qualified identity joins from any location. A named
    home that does not exist joins nothing.
    """
    if named_homes is None:
        reach = resolve_default_read_set(
            caller,
            landed_home=landing.home,
            current_project_company=landing.project_company,
            role_resolver=role_resolver,
        )
    else:
        reach = {
            key: resolve_caller_read_depth(caller, key, role_resolver=role_resolver)
            for key in named_homes
            if resolver.resolve(key) is not None
        }
    for snippet_id in snippet_ids or []:
        requested_home = home_tier_for_snippet_id(snippet_id)
        if requested_home is None or requested_home in reach or resolver.resolve(requested_home) is None:
            continue
        reach[requested_home] = resolve_caller_read_depth(caller, requested_home, role_resolver=role_resolver)
    return reach


def _load_reached_snippets(
    *,
    reach: Mapping[TierKey, TierDepth],
    named: bool,
    resolver: HomeResolver,
    global_root: Path,
) -> tuple[list[SnippetMeta], set[Path]]:
    """Load global material and both halves of every reached home; return them with the reached project roots.

    A home's published half arrives through the merged global index; its local
    half is loaded from the home's own local catalog. With named homes, global
    material is limited to the domains a named project publishes as owner.
    """
    homes = [home for home in (resolver.resolve(key) for key in reach) if home is not None]
    owned_domains: set[str] = set()
    if named:
        for home in homes:
            if home.tier.scope is SnippetScope.PROJECT:
                owned_domains |= publishes_for_root(home.root)

    snippets: list[SnippetMeta] = []
    global_index = GLOBAL_DOCS_DIR / _INDEX_FILENAME
    for snippet in _load_index(global_index, source_project=GLOBAL_SOURCE_PROJECT, project_root=global_root):
        if snippet.scope == SnippetScope.PROJECT.value:
            # The published tree carries no project's local identity.
            continue
        if snippet.scope in _HOME_SCOPE_VALUES:
            if _tier_key_for_snippet(snippet) in reach:
                snippets.append(snippet)
            continue
        if not named or snippet.domain in owned_domains:
            snippets.append(snippet)

    for home in homes:
        snippets.extend(_load_home_local(home))
    project_roots = {home.root for home in homes if home.tier.scope is SnippetScope.PROJECT}
    return snippets, project_roots


def _load_third_party_entries(project_root: Path) -> list[ThirdPartyMeta]:
    """Load the mother's and the landed project's third-party indexes (outside the taxonomy).

    Global third-party docs live in the mother repo's source tree
    (``<repo>/docs/third-party``), not under the deployed docs root. In the
    mother repo both indexes are the same file, so it is loaded once.
    """
    project_third_party_index = project_root / "docs" / "third-party" / _INDEX_FILENAME
    global_third_party_index = REPO_ROOT / "docs" / "third-party" / _INDEX_FILENAME
    entries = list(load_third_party_index(global_third_party_index))
    if project_third_party_index.resolve() != global_third_party_index.resolve():
        entries.extend(load_third_party_index(project_third_party_index))
    return entries


def _selection_source(landing: Landing, named_homes: list[TierKey] | None) -> DocsSelectionSource:
    if named_homes is not None and any(key.scope is SnippetScope.PROJECT for key in named_homes):
        return DocsSelectionSource.EXPLICIT_PROJECT
    if landing.project_slug is not None:
        return DocsSelectionSource.CURRENT_PROJECT
    if landing.home is not None:
        return DocsSelectionSource.LANDED_HOME
    return DocsSelectionSource.NO_HOME


def _assemble_candidate_snippets(
    *,
    project_root: Path,
    landing: Landing,
    named_homes: list[TierKey] | None,
    caller: CliCaller | None,
    role_resolver: RoleResolver,
    snippet_ids: list[str] | None,
    include_third_party: bool,
) -> AssembledCandidates:
    """Load global material and both halves of every home in reach into one candidate list."""
    global_root = GLOBAL_DOCS_DIR.parent.parent
    resolver = HomeResolver(landed=landing.catalog())
    reach = _resolve_reach(
        landing=landing,
        named_homes=named_homes,
        caller=caller,
        role_resolver=role_resolver,
        resolver=resolver,
        snippet_ids=snippet_ids,
    )
    snippets, project_roots = _load_reached_snippets(
        reach=reach, named=named_homes is not None, resolver=resolver, global_root=global_root
    )

    if landing.project_company and named_homes is None and not (COMPANIES_ROOT / landing.project_company).exists():
        # Declared-but-unknown company: surface the misconfiguration rather than
        # silently resolving no relationship (indistinguishable from a correctly
        # no-company project).
        logger.warning("project_company_unknown", company=landing.project_company, companies_root=str(COMPANIES_ROOT))

    if snippet_ids and any(sid.startswith("third-party/") for sid in snippet_ids):
        include_third_party = True
    third_party_entries = _load_third_party_entries(project_root) if include_third_party else []

    return AssembledCandidates(
        snippets=snippets,
        snippets_by_path={str(s.path): s for s in snippets},
        all_loaded_ids={snippet.snippet_id for snippet in snippets},
        third_party_entries=third_party_entries,
        current_project_slug=landing.project_slug,
        reach=reach,
        project_roots=project_roots,
        source_reason=_selection_source(landing, named_homes),
        global_root=global_root,
        named=named_homes is not None,
    )


def _apply_content_selection_filters(
    snippets: list[SnippetMeta],
    third_party_entries: list[ThirdPartyMeta],
    *,
    scope: SnippetScope | None,
    named: bool,
    domains: list[str] | None,
    snippet_ids: list[str] | None,
    target_slug: str | None,
) -> tuple[list[SnippetMeta], list[ThirdPartyMeta]]:
    """Narrow the assembled list by scope, domain, and target.

    Each only narrows. ``--scope project`` already assembled exactly one project
    home's owned set, so it applies no further scope equality; every other scope
    keeps its own snippets. Named homes carry no third-party material.
    """
    if scope is not None and scope is not SnippetScope.PROJECT:
        snippets = [snippet for snippet in snippets if snippet.scope == scope]
        third_party_entries = [entry for entry in third_party_entries if entry.scope == scope]
    if named:
        # Third-party indexes are loaded for the landed location + global only and
        # are never loaded for a named home (mirrors the target-slug branch below).
        third_party_entries = []

    if domains:
        # Narrow the assembled list to the requested published domains. A home
        # snippet's domain is its kind literal, so it falls outside any
        # published domain and drops out.
        requested_domains = set(domains)
        snippets = [snippet for snippet in snippets if snippet.domain in requested_domains]
        third_party_entries = []

    if not snippet_ids and target_slug is not None:
        # Index --target: focus on one todo's pending work — both the not-yet-live
        # NEW snippets it delivers and the LIVE snippets it reworks via planned
        # sections / companions. Without a target the listing shows everything,
        # flagging pending work inline via the (delivered by:) / (superseded by:)
        # suffixes rather than hiding it.
        snippets = [
            snippet
            for snippet in snippets
            if target_slug in snippet.delivered_by or target_slug in snippet.superseded_by
        ]
        third_party_entries = []

    return snippets, third_party_entries


def build_context_output(  # TODO: refactor to reduce complexity
    *,
    areas: list[str],
    project_root: Path,
    snippet_ids: list[str] | None = None,
    baseline_only: bool = False,
    include_third_party: bool = False,
    domains: list[str] | None = None,
    list_projects: bool = False,
    projects: list[str] | None = None,
    person: str | None = None,
    company: str | None = None,
    caller: CliCaller | None = None,
    config: AppConfig | None = None,
    test_agent: str | None = None,
    test_mode: str | None = None,
    test_request: str | None = None,
    test_csv_path: str | None = None,
    target_slug: str | None = None,
    scope: SnippetScope | None = None,
    closure: bool = False,
    landing_kind: ConfigKind | None = None,
    retrieval_id: str | None = None,
    verb: str | None = None,
) -> str:
    if list_projects:
        return _build_project_catalog_output()
    if closure:
        _validate_activation_closure_request(
            snippet_ids=snippet_ids,
            scope=scope,
            projects=projects,
            target_slug=target_slug,
        )

    global_snippets_root = GLOBAL_DOCS_DIR

    role_resolver = RoleResolver()
    landing = resolve_landing(project_root, landing_kind=landing_kind, config=config)
    assembled = _assemble_candidate_snippets(
        project_root=project_root,
        landing=landing,
        named_homes=_named_homes(projects=projects, person=person, company=company, scope=scope, landing=landing),
        caller=caller,
        role_resolver=role_resolver,
        snippet_ids=snippet_ids,
        include_third_party=include_third_party,
    )
    snippets = assembled.snippets
    snippets_by_path = assembled.snippets_by_path
    all_loaded_ids = assembled.all_loaded_ids
    third_party_entries = assembled.third_party_entries
    current_project_slug = assembled.current_project_slug
    source_reason = assembled.source_reason
    global_root = assembled.global_root
    read_set = assembled.reach
    named_project_slugs = {
        key.owner for key in read_set if key.scope is SnippetScope.PROJECT and key.owner != current_project_slug
    }

    include_snippet = _include_snippet_factory(caller=caller, read_set=read_set, role_resolver=role_resolver)
    snippets = [snippet for snippet in snippets if include_snippet(snippet)]
    snippets = _apply_baseline_filter(
        snippets,
        baseline_only=baseline_only,
        global_root=global_root,
        snippets_by_path=snippets_by_path,
        project_roots=assembled.project_roots,
    )
    snippets, third_party_entries = _apply_content_selection_filters(
        snippets,
        third_party_entries,
        scope=scope,
        named=assembled.named,
        domains=domains,
        snippet_ids=snippet_ids,
        target_slug=target_slug,
    )

    areas_set = set(areas)
    if areas_set:
        snippets_for_selection = [s for s in snippets if s.snippet_type in areas_set]
    else:
        snippets_for_selection = list(snippets)

    if not snippet_ids:
        counts = _selection_counts(
            snippets_for_selection,
            current_project_slug=current_project_slug,
            other_project_slugs=named_project_slugs,
        )
        _emit_selection_summary(
            retrieval_id=retrieval_id,
            verb=verb,
            source_reason=source_reason,
            selection_outcome=DocsSelectionOutcome.SUCCEEDED if snippets_for_selection else DocsSelectionOutcome.EMPTY,
            counts=counts,
            denied_count=0,
            rendered_count=0,
            target_delivered_count=sum(target_slug in snippet.delivered_by for snippet in snippets_for_selection),
            target_superseded_count=sum(target_slug in snippet.superseded_by for snippet in snippets_for_selection),
            dependency_count=0,
        )
        return _build_phase1_output(
            snippets_for_selection,
            third_party_entries,
            areas=areas,
            read_set=read_set,
            test_agent=test_agent,
            test_mode=test_mode,
            test_request=test_request,
            test_csv_path=test_csv_path,
        )

    # Build valid IDs from both taxonomy snippets and third-party entries
    valid_ids = {s.snippet_id for s in snippets}
    third_party_by_id = {e.snippet_id: e for e in third_party_entries}
    valid_ids.update(third_party_by_id.keys())

    selected_ids, denied_ids, unknown_ids, taxonomy_ids, third_party_ids = _partition_selected_ids(
        snippet_ids,
        valid_ids,
        all_loaded_ids,
        third_party_by_id,
    )
    closure_root: SnippetMeta | None = None
    if closure:
        closure_root = (
            next((snippet for snippet in snippets if snippet.snippet_id == taxonomy_ids[0]), None)
            if taxonomy_ids
            else None
        )
        _validate_activation_closure_request(
            snippet_ids=snippet_ids,
            scope=scope,
            projects=projects,
            target_slug=target_slug,
            root=closure_root,
            validate_root=True,
        )
    if unknown_ids:
        _emit_selection_summary(
            retrieval_id=retrieval_id,
            verb=verb,
            source_reason=source_reason,
            selection_outcome=DocsSelectionOutcome.UNKNOWN,
            counts=_selection_counts(
                snippets, current_project_slug=current_project_slug, other_project_slugs=named_project_slugs
            ),
            denied_count=len(denied_ids),
            rendered_count=0,
            target_delivered_count=0,
            target_superseded_count=0,
            dependency_count=0,
        )
        return f"ERROR: Unknown snippet IDs: {', '.join(unknown_ids)}"

    resolved = _resolve_requires(taxonomy_ids, snippets)
    _write_test_output(
        phase="phase2",
        areas=areas,
        index_ids=[],
        selected_ids=selected_ids,
        test_agent=test_agent,
        test_mode=test_mode,
        test_request=test_request,
        test_csv_path=test_csv_path,
    )

    logger.debug(
        "context_selector_output_summary",
        selected_ids_count=len(selected_ids),
        resolved_snippets_count=len(resolved),
    )

    requested_set = set(selected_ids)
    dep_ids = [s.snippet_id for s in resolved if s.snippet_id not in requested_set]
    body_parts, rendered_count, rendered_dependency_ids = _render_phase2_taxonomy_bodies(
        resolved=resolved,
        requested_set=requested_set,
        closure_root=closure_root,
        project_root=project_root,
        global_root=global_root,
        global_snippets_root=global_snippets_root,
        target_slug=target_slug,
    )

    parts: list[str] = [
        "# PHASE 2: Selected snippet content",
        f"# Requested: {', '.join(selected_ids)}",
    ]
    if closure:
        if rendered_dependency_ids:
            parts.append(f"# Required reads (included): {', '.join(rendered_dependency_ids)}")
    elif dep_ids:
        parts.append(f"# Required reads (not loaded) that MUST have been read AT LEAST ONCE: {', '.join(dep_ids)}")
    parts.append("")
    parts.extend(body_parts)

    # Output selected third-party entries (no type, no dependency resolution)
    if third_party_ids:
        parts.append("")
        parts.append("# Third-party documentation")
        for sid in third_party_ids:
            entry = third_party_by_id.get(sid)
            if not entry:
                continue
            try:
                raw = entry.path.read_text(encoding="utf-8")
                _, body = split_frontmatter(raw)
            except Exception as exc:
                logger.exception("context_selector_read_failed", path=str(entry.path), error=str(exc))
                continue
            parts.append(
                "\n".join(
                    [
                        "---",
                        f"id: {entry.snippet_id}",
                        f"scope: {entry.scope}",
                        f"description: {entry.description}",
                        "---",
                    ]
                ).strip()
            )
            parts.append(body.lstrip("\n"))
            rendered_count += 1

    # Emit access-denied notices for snippets the caller's role cannot see
    for sid in denied_ids:
        parts.append(
            "\n".join(
                [
                    "---",
                    f"id: {sid}",
                    "access: denied",
                    "reason: Insufficient role for current session.",
                    "---",
                ]
            ).strip()
        )

    _emit_selection_summary(
        retrieval_id=retrieval_id,
        verb=verb,
        source_reason=source_reason,
        selection_outcome=DocsSelectionOutcome.DENIED
        if denied_ids and rendered_count == 0
        else DocsSelectionOutcome.SUCCEEDED,
        counts=_selection_counts(
            snippets, current_project_slug=current_project_slug, other_project_slugs=named_project_slugs
        ),
        denied_count=len(denied_ids),
        rendered_count=rendered_count,
        target_delivered_count=0,
        target_superseded_count=0,
        dependency_count=len(rendered_dependency_ids) if closure else len(dep_ids),
    )
    return "\n".join(parts)
