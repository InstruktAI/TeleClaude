"""Context selector for agent injection and tool schema resolution."""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.config.loader import load_project_config
from teleclaude.config.schema import AppConfig
from teleclaude.constants import DOMAIN_SCOPES, HUMAN_ROLE_ADMIN, SNIPPET_VISIBILITY_INTERNAL, TAXONOMY_TYPES
from teleclaude.doc_body import (
    INLINE_REF_RE,
    apply_planned_change_sections,
    apply_planned_sections,
    resolve_inline_refs,
    split_frontmatter,
)
from teleclaude.docs_index import extract_required_reads, get_project_slug
from teleclaude.paths import GLOBAL_SNIPPETS_DIR, REPO_ROOT
from teleclaude.required_reads import strip_required_reads_section
from teleclaude.services.project_catalog import get_project_catalog_service
from teleclaude.slug import normalize_slug
from teleclaude.snippet_validation import SnippetScope, companion_slug
from teleclaude.third_party_index import ThirdPartyMeta, load_third_party_index
from teleclaude.utils import resolve_project_config_path

logger = get_logger(__name__)

SCOPE_ORDER = {"global": 0, "project": 1}


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
    delivered_by: tuple[str, ...] = ()
    superseded_by: tuple[str, ...] = ()


def _scope_rank(scope: str | None) -> int:
    if not scope:
        return 3
    return SCOPE_ORDER.get(scope, 3)


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
    if not os.getenv(_TEST_ENABLED_ENV):
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


def _resolve_domain_paths(domains: dict[str, str], project_root: Path) -> dict[str, Path]:
    """Convert domain string paths to resolved absolute Paths."""
    if not domains:
        return {"software-development": project_root / "docs"}
    clean_map: dict[str, Path] = {}
    for key, value in domains.items():
        if not key.strip():
            continue
        if value.strip():
            candidate = (project_root / value).resolve()
        else:
            candidate = (project_root / "docs").resolve()
        clean_map[key] = candidate
    return clean_map or {"software-development": project_root / "docs"}


def _load_project_domains(project_root: Path) -> dict[str, Path]:
    config_path = resolve_project_config_path(project_root)
    if not config_path.exists():
        return {"software-development": project_root / "docs"}

    try:
        config = load_project_config(config_path)
        domains = config.business.domains
    except Exception as e:
        logger.error("project config validation failed", path=str(config_path), error=str(e))
        raise

    return _resolve_domain_paths(domains, project_root)


def _load_manifest_by_name() -> dict[str, tuple[Path, Path, str]]:
    """Return {slug: (index_path, project_root, slug)} for all registered projects."""
    catalog = get_project_catalog_service()
    projects: dict[str, tuple[Path, Path, str]] = {}
    for node in catalog.list_projects():
        projects[node.slug] = (node.docs_index_path, node.root, node.slug)
    return projects


def _is_cross_project_snippet_id(snippet_id: str, *, domain_prefixes: set[str]) -> bool:
    if "/" not in snippet_id:
        return False
    prefix = snippet_id.split("/", 1)[0].strip().lower()
    if not prefix:
        return False
    if prefix in {"project", "general", "third-party", "baseline"}:
        return False
    if prefix in domain_prefixes:
        return False
    return True


def _load_index(
    index_path: Path,
    *,
    source_project: str = "",
    rewrite_project_prefix: bool = False,
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
                    delivered_by=delivered_by,
                    superseded_by=superseded_by,
                )
            )
        _index_cache[cache_key] = (mtime, loaded_entries)
        base_entries = loaded_entries

    entries: list[SnippetMeta] = []
    for snippet in base_entries:
        snippet_id = snippet.snippet_id
        if rewrite_project_prefix and snippet_id.startswith("project/"):
            snippet_id = f"{source_project.lower()}/{snippet_id[len('project/') :]}"
        entries.append(
            SnippetMeta(
                snippet_id=snippet_id,
                description=snippet.description,
                snippet_type=snippet.snippet_type,
                scope=snippet.scope,
                domain=snippet.domain,
                path=snippet.path,
                source_project=source_project or snippet.source_project,
                project_root=project_root or snippet.project_root,
                visibility=snippet.visibility or SNIPPET_VISIBILITY_INTERNAL,
                delivered_by=snippet.delivered_by,
                superseded_by=snippet.superseded_by,
            )
        )

    return entries


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
            (e.g. the global baseline at ``REPO_ROOT/docs/global/baseline.md``).
            Absence or read failure raises rather than degrading to an empty
            set, so silent context drop becomes a hard error.

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


def _load_selected_snippets(
    *,
    project_root: Path,
    projects: list[str] | None,
    project_index: Path,
    global_index: Path,
    global_root: Path,
    current_project_slug: str,
    manifest_projects: dict[str, tuple[Path, Path, str]],
) -> list[SnippetMeta]:
    snippets = _load_index(
        global_index,
        source_project="global",
        rewrite_project_prefix=False,
        project_root=global_root,
    )
    if not projects:
        snippets.extend(
            _load_index(
                project_index,
                source_project=current_project_slug,
                rewrite_project_prefix=False,
                project_root=project_root,
            )
        )
        return snippets

    seen_projects: set[str] = set()
    for project_name in projects:
        project_key = project_name.strip().lower()
        if not project_key or project_key in seen_projects:
            continue
        seen_projects.add(project_key)
        manifest_entry = manifest_projects.get(project_key)
        if manifest_entry:
            snippets.extend(_load_manifest_index(*manifest_entry))
    return snippets


def _load_manifest_index(index_path: Path, manifest_root: Path, canonical_name: str) -> list[SnippetMeta]:
    return _load_index(
        index_path,
        source_project=canonical_name,
        rewrite_project_prefix=True,
        project_root=manifest_root,
    )


def _load_cross_project_snippets(
    *,
    snippets: list[SnippetMeta],
    snippet_ids: list[str] | None,
    domain_config: dict[str, Path],
    manifest_projects: dict[str, tuple[Path, Path, str]],
    snippets_by_path: dict[str, SnippetMeta],
) -> set[str]:
    all_loaded_ids = {snippet.snippet_id for snippet in snippets}
    if not snippet_ids:
        return all_loaded_ids
    domain_prefixes = {name.lower() for name in domain_config.keys()}
    prefixes_to_load = {
        sid.split("/", 1)[0].strip().lower()
        for sid in snippet_ids
        if _is_cross_project_snippet_id(sid, domain_prefixes=domain_prefixes)
    }
    already_loaded = {snippet.source_project.lower() for snippet in snippets if snippet.source_project}
    for project_key in prefixes_to_load:
        if project_key in already_loaded:
            continue
        manifest_entry = manifest_projects.get(project_key)
        if not manifest_entry:
            continue
        loaded = _load_manifest_index(*manifest_entry)
        snippets.extend(loaded)
        for snippet in loaded:
            snippets_by_path[str(snippet.path)] = snippet
            all_loaded_ids.add(snippet.snippet_id)
    return all_loaded_ids


def _include_snippet_factory(
    *,
    effective_human_role: str | None,
    requested_ids: set[str],
    projects: list[str] | None,
    current_project_slug: str,
    global_snippets_root: Path,
    domain_config: dict[str, Path],
    project_domain_roots: dict[str, Path],
) -> Callable[[SnippetMeta], bool]:
    def _include(snippet: SnippetMeta) -> bool:
        if effective_human_role != HUMAN_ROLE_ADMIN and snippet.visibility != "public":
            return False
        if global_snippets_root in snippet.path.parents:
            return snippet.snippet_id.startswith("general/") or any(
                snippet.snippet_id.startswith(f"{domain}/") for domain in domain_config
            )
        if snippet.scope != "project":
            return True
        is_cross_project = bool(snippet.source_project) and snippet.source_project.lower() != current_project_slug
        if requested_ids and snippet.snippet_id in requested_ids and is_cross_project:
            return True
        if projects and is_cross_project:
            return True
        return any(
            root in snippet.path.parents or root == snippet.path.parent for root in project_domain_roots.values()
        )

    return _include


def _apply_baseline_filter(
    snippets: list[SnippetMeta],
    *,
    baseline_only: bool,
    project_root: Path,
    global_root: Path,
    snippets_by_path: dict[str, SnippetMeta],
) -> list[SnippetMeta]:
    if not baseline_only:
        return snippets
    baseline_ids: set[str] = set()
    # The global manifest is owned by the TeleClaude mother repo at
    # `docs/global/baseline.md` (per the baseline-snippet-manifests spec).
    # Read it from `REPO_ROOT` rather than the deployed snippets dir; the
    # latter intentionally does not carry the raw @-ref manifest.
    baseline_ids.update(
        _load_baseline_ids(
            REPO_ROOT / "docs" / "global" / "baseline.md",
            snippets_by_path,
            project_root=global_root,
            required=True,
        )
    )
    baseline_ids.update(
        _load_baseline_ids(
            project_root / "docs" / "project" / "baseline.md", snippets_by_path, project_root=project_root
        )
    )
    return [snippet for snippet in snippets if snippet.snippet_id in baseline_ids]


def _build_phase1_output(
    snippets_for_selection: list[SnippetMeta],
    third_party_entries: list[ThirdPartyMeta],
    *,
    areas: list[str],
    test_agent: str | None,
    test_mode: str | None,
    test_request: str | None,
    test_csv_path: str | None,
) -> str:
    parts = [
        "# PHASE 1: Snippet Index (IDs + descriptions)",
        "# Review the snippets below and select the IDs you need.",
        f"# Filter with --areas <{'|'.join(TAXONOMY_TYPES)}> and/or --domains <{'|'.join(DOMAIN_SCOPES)}> (omit for all)",
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


def build_context_output(  # noqa: C901 # TODO: refactor to reduce complexity
    *,
    areas: list[str],
    project_root: Path,
    snippet_ids: list[str] | None = None,
    baseline_only: bool = False,
    include_third_party: bool = False,
    domains: list[str] | None = None,
    list_projects: bool = False,
    projects: list[str] | None = None,
    effective_human_role: str | None = None,
    config: AppConfig | None = None,
    test_agent: str | None = None,
    test_mode: str | None = None,
    test_request: str | None = None,
    test_csv_path: str | None = None,
    target_slug: str | None = None,
    scope: SnippetScope | None = None,
) -> str:
    if list_projects:
        return _build_project_catalog_output()

    project_index = project_root / "docs" / "project" / "index.yaml"
    global_index = GLOBAL_SNIPPETS_DIR / "index.yaml"
    global_root = GLOBAL_SNIPPETS_DIR.parent.parent
    global_snippets_root = GLOBAL_SNIPPETS_DIR

    # Resolve project slug from config when available (avoids interior config loading).
    # The slug is the canonical cross-project identity: comparisons against
    # ``snippet.source_project`` and cross-project prefix matching are all
    # slug-based after the catalog service migration.
    #
    # When ``config`` is supplied but ``config.project`` is ``None`` (person
    # workspace), ``teleclaude.yml`` is not a ``ProjectConfig`` and must not
    # be re-read by ``get_project_slug`` — fall back to the directory name.
    if config is not None:
        if config.project is not None:
            current_project_slug = config.project.project_slug or normalize_slug(
                config.project.project_name or project_root.name
            )
        else:
            current_project_slug = normalize_slug(project_root.name)
    else:
        current_project_slug = get_project_slug(project_root)

    manifest_projects = _load_manifest_by_name() if (projects or snippet_ids) else {}

    # Third-party indexes (separate from taxonomy). Global third-party docs live in
    # the mother repo's source tree (``<repo>/docs/third-party``), not under the
    # whole-tree docs symlink at ``~/.teleclaude/docs`` (which points at docs/global).
    project_third_party_index = project_root / "docs" / "third-party" / "index.yaml"
    global_third_party_index = REPO_ROOT / "docs" / "third-party" / "index.yaml"

    snippets = _load_selected_snippets(
        project_root=project_root,
        projects=projects,
        project_index=project_index,
        global_index=global_index,
        global_root=global_root,
        current_project_slug=current_project_slug,
        manifest_projects=manifest_projects,
    )

    # Build path-to-snippet mapping for baseline resolution
    snippets_by_path = {str(s.path): s for s in snippets}

    # Auto-enable third-party loading when snippet_ids reference them
    if snippet_ids and any(sid.startswith("third-party/") for sid in snippet_ids):
        include_third_party = True

    # Load third-party entries (separate from taxonomy, not filtered by areas)
    third_party_entries: list[ThirdPartyMeta] = []
    if include_third_party:
        third_party_entries.extend(load_third_party_index(global_third_party_index))
        # In the mother repo the project IS the global source, so both indexes
        # resolve to the same file — load the project index only when it differs,
        # otherwise every third-party entry would be listed twice (phase-1 output
        # does not dedup).
        if project_third_party_index.resolve() != global_third_party_index.resolve():
            third_party_entries.extend(load_third_party_index(project_third_party_index))

    # Use explicit domains if provided; else use config when available; else load from project config
    if domains:
        domain_config = {d: project_root / "docs" for d in domains}
    elif config is not None and config.project is not None:
        domain_config = _resolve_domain_paths(config.project.business.domains, project_root)
    elif config is not None and config.project is None:
        domain_config = {"software-development": project_root / "docs"}
    else:
        domain_config = _load_project_domains(project_root)
    project_domain_roots = {d: p for d, p in domain_config.items() if p.exists()}
    if not project_domain_roots:
        project_domain_roots = {d: project_root / "docs" for d in domain_config.keys()}

    all_loaded_ids = _load_cross_project_snippets(
        snippets=snippets,
        snippet_ids=snippet_ids,
        domain_config=domain_config,
        manifest_projects=manifest_projects,
        snippets_by_path=snippets_by_path,
    )

    requested_ids = {sid.strip() for sid in (snippet_ids or []) if sid.strip()}
    include_snippet = _include_snippet_factory(
        effective_human_role=effective_human_role,
        requested_ids=requested_ids,
        projects=projects,
        current_project_slug=current_project_slug,
        global_snippets_root=global_snippets_root,
        domain_config=domain_config,
        project_domain_roots=project_domain_roots,
    )
    snippets = [snippet for snippet in snippets if include_snippet(snippet)]
    snippets = _apply_baseline_filter(
        snippets,
        baseline_only=baseline_only,
        project_root=project_root,
        global_root=global_root,
        snippets_by_path=snippets_by_path,
    )
    # Content-selection filters: narrow the assembled list by scope tier and/or
    # queried project. Both suppress the otherwise-unconditional global include so
    # the filter actually narrows. They apply to the single taxonomy list (feeding
    # both phase-1 and phase-2) and to the parallel third-party track.
    if scope is not None:
        snippets = [snippet for snippet in snippets if snippet.scope == scope]
        third_party_entries = [entry for entry in third_party_entries if entry.scope == scope]
    if projects:
        project_keys = {name.strip().lower() for name in projects if name.strip()}
        snippets = [snippet for snippet in snippets if snippet.source_project.lower() in project_keys]
        # Third-party indexes are loaded for the current project + global only and
        # are never cross-project-loaded, so none belong to a queried foreign
        # project (mirrors the target-slug branch below).
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

    areas_set = set(areas)
    if areas_set:
        snippets_for_selection = [s for s in snippets if s.snippet_type in areas_set]
    else:
        snippets_for_selection = list(snippets)

    if not snippet_ids:
        return _build_phase1_output(
            snippets_for_selection,
            third_party_entries,
            areas=areas,
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
    if unknown_ids:
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
    parts: list[str] = [
        "# PHASE 2: Selected snippet content",
        f"# Requested: {', '.join(selected_ids)}",
    ]
    if dep_ids:
        parts.append(f"# Required reads (not loaded) that MUST have been read AT LEAST ONCE: {', '.join(dep_ids)}")
    parts.append("")

    for snippet in resolved:
        if snippet.snippet_id not in requested_set:
            continue
        body = _read_selected_snippet_body(
            snippet,
            project_root=project_root,
            global_root=global_root,
            global_snippets_root=global_snippets_root,
            target_slug=target_slug,
        )
        if body is None:
            continue
        parts.append(
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
        parts.append(body.lstrip("\n"))
        if snippet.superseded_by and target_slug is None:
            parts.extend(_pending_changes_awareness_lines(snippet))

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

    return "\n".join(parts)
