from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.config.loader import load_project_config
from teleclaude.constants import SNIPPET_VISIBILITY_INTERNAL
from teleclaude.docs_index import extract_required_reads, get_project_name
from teleclaude.paths import GLOBAL_SNIPPETS_DIR
from teleclaude.project_manifest import load_manifest
from teleclaude.required_reads import strip_required_reads_section
from teleclaude.utils import resolve_project_config_path

logger = get_logger(__name__)

SCOPE_ORDER = {"global": 0, "domain": 0, "project": 1}


@dataclass(frozen=True)
class SnippetMeta:
    snippet_id: str
    description: str
    snippet_type: str
    scope: str
    path: Path
    source_project: str = ""
    project_root: Path | None = None
    visibility: str = SNIPPET_VISIBILITY_INTERNAL


@dataclass(frozen=True)
class ThirdPartyMeta:
    """Third-party doc entry - no type field (not part of taxonomy)."""

    snippet_id: str
    description: str
    scope: str
    path: Path


def _scope_rank(scope: str | None) -> int:
    if not scope:
        return 3
    return SCOPE_ORDER.get(scope, 3)


_INLINE_REF_RE = re.compile(r"@([\w./~\-]+\.md)")

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
        with open(csv_path, "r", encoding="utf-8") as handle:
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


def _split_frontmatter(content: str) -> tuple[str, str]:
    """Split frontmatter header from body, preserving header verbatim."""
    if not content.startswith("---"):
        return "", content
    lines = content.splitlines(keepends=True)
    if not lines:
        return "", content
    # Find the closing frontmatter fence.
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            head = "".join(lines[: idx + 1])
            body = "".join(lines[idx + 1 :])
            return head, body
    return "", content


def _domain_for_snippet(snippet: SnippetMeta, *, project_domains: dict[str, Path]) -> str:
    snippet_id = snippet.snippet_id
    for domain, root in project_domains.items():
        if root in snippet.path.parents or root == snippet.path.parent:
            return domain
    if snippet.source_project:
        prefix = f"{snippet.source_project.lower()}/"
        if snippet_id.lower().startswith(prefix):
            remainder = snippet_id[len(prefix) :]
            return remainder.split("/", 1)[0] if remainder else snippet.source_project.lower()
    return snippet_id.split("/", 1)[0] if "/" in snippet_id else snippet_id


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


def _output_scope(snippet: SnippetMeta, *, global_snippets_root: Path) -> str:
    if global_snippets_root in snippet.path.parents:
        return "global"
    return "project"


def _load_manifest_by_name() -> dict[str, tuple[Path, Path, str]]:
    """Map lowercase project name to (index_path, project_root, canonical_name)."""
    projects: dict[str, tuple[Path, Path, str]] = {}
    for entry in load_manifest():
        key = entry.name.strip().lower()
        if not key:
            continue
        projects[key] = (
            Path(entry.index_path).expanduser().resolve(),
            Path(entry.project_root).expanduser().resolve(),
            entry.name,
        )
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


def _resolve_inline_refs(content: str, *, snippet_path: Path, root_path: Path) -> str:
    """Expand @<path>.md references to absolute paths for tool consumption."""
    head, body = _split_frontmatter(content)

    def _expand(match: re.Match[str]) -> str:
        ref = match.group(1)
        if "://" in ref:
            return match.group(0)
        candidate = Path(ref).expanduser()
        if not candidate.is_absolute():
            if str(candidate).startswith("docs/"):
                candidate = (root_path / candidate).resolve()
            else:
                candidate = (snippet_path.parent / candidate).resolve()
        else:
            candidate = candidate.resolve()
        return f"@{candidate}"

    return f"{head}{_INLINE_REF_RE.sub(_expand, body)}"


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
            raw_path = item.get("path")
            if (
                not isinstance(snippet_id, str)
                or not isinstance(description, str)
                or not isinstance(snippet_type, str)
                or not isinstance(scope, str)
                or not isinstance(raw_path, str)
            ):
                continue
            path = Path(raw_path).expanduser()
            if not path.is_absolute():
                path = (root_path / path).resolve()
            raw_visibility = item.get("visibility")
            visibility = raw_visibility if isinstance(raw_visibility, str) else SNIPPET_VISIBILITY_INTERNAL
            raw_source_project = item.get("source_project")
            loaded_entries.append(
                SnippetMeta(
                    snippet_id=snippet_id,
                    description=description,
                    snippet_type=snippet_type,
                    scope=scope,
                    path=path,
                    source_project=raw_source_project if isinstance(raw_source_project, str) else "",
                    project_root=root_path,
                    visibility=visibility,
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
                path=snippet.path,
                source_project=source_project or snippet.source_project,
                project_root=project_root or snippet.project_root,
                visibility=snippet.visibility or SNIPPET_VISIBILITY_INTERNAL,
            )
        )

    return entries


def _load_baseline_ids(
    baseline_path: Path,
    snippets_by_path: dict[str, SnippetMeta],
    *,
    project_root: Path,
) -> set[str]:
    """Load baseline manifest and return referenced snippet IDs.

    Args:
        baseline_path: Path to baseline.md manifest file
        snippets_by_path: Mapping of resolved paths to snippets
        project_root: Project root for resolving relative paths

    Returns:
        Set of snippet IDs referenced in the baseline manifest
    """
    if not baseline_path.exists():
        return set()

    try:
        content = baseline_path.read_text(encoding="utf-8")
    except Exception:
        return set()

    baseline_ids: set[str] = set()
    for match in _INLINE_REF_RE.finditer(content):
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


def _load_third_party_index(index_path: Path) -> list[ThirdPartyMeta]:
    """Load third-party index.yaml (simpler schema: no type field)."""
    if not index_path.exists():
        return []

    try:
        payload = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.exception("third_party_index_load_failed", path=str(index_path), error=str(exc))
        return []

    if not isinstance(payload, dict):
        return []

    snippets_root = payload.get("snippets_root")
    snippets = payload.get("snippets")
    if not isinstance(snippets_root, str) or not isinstance(snippets, list):
        return []

    root_path = Path(snippets_root).expanduser().resolve()
    entries: list[ThirdPartyMeta] = []
    for item in snippets:
        if not isinstance(item, dict):
            continue
        snippet_id = item.get("id")
        description = item.get("description")
        scope = item.get("scope")
        raw_path = item.get("path")
        if (
            not isinstance(snippet_id, str)
            or not isinstance(description, str)
            or not isinstance(scope, str)
            or not isinstance(raw_path, str)
        ):
            continue
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = (root_path / path).resolve()
        entries.append(
            ThirdPartyMeta(
                snippet_id=snippet_id,
                description=description,
                scope=scope,
                path=path,
            )
        )

    return entries


def _resolve_requires(
    selected_ids: Iterable[str],
    snippets: list[SnippetMeta],
    *,
    global_snippets_root: Path,
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
        except Exception:
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

    resolved.sort(
        key=lambda s: (_scope_rank(_output_scope(s, global_snippets_root=global_snippets_root)), s.snippet_id)
    )
    return resolved


def build_context_output(
    *,
    areas: list[str],
    project_root: Path,
    snippet_ids: list[str] | None = None,
    baseline_only: bool = False,
    include_third_party: bool = False,
    domains: list[str] | None = None,
    list_projects: bool = False,
    projects: list[str] | None = None,
    caller_role: str = "admin",
    human_role: str | None = None,
    test_agent: str | None = None,
    test_mode: str | None = None,
    test_request: str | None = None,
    test_csv_path: str | None = None,
) -> str:
    if list_projects:
        manifest_entries = sorted(load_manifest(), key=lambda entry: entry.name.lower())
        parts = [
            "# PHASE 0: Project Catalog",
            "# Available projects registered in ~/.teleclaude/projects.yaml",
            "",
        ]
        if not manifest_entries:
            parts.append("No registered projects found.")
        else:
            for entry in manifest_entries:
                description = entry.description or "(no description)"
                parts.append(f"{entry.name.lower()}: {description}")
        parts.extend(
            [
                "",
                "# ⚠️  IMPORTANT: Call teleclaude__get_context again with projects=[...] to browse snippet indexes.",
            ]
        )
        return "\n".join(parts)

    project_index = project_root / "docs" / "project" / "index.yaml"
    global_index = GLOBAL_SNIPPETS_DIR / "index.yaml"
    global_root = GLOBAL_SNIPPETS_DIR.parent.parent
    global_snippets_root = GLOBAL_SNIPPETS_DIR
    current_project_name = get_project_name(project_root)
    manifest_projects = _load_manifest_by_name() if (projects or snippet_ids) else {}

    # Third-party indexes (separate from taxonomy)
    project_third_party_index = project_root / "docs" / "third-party" / "index.yaml"
    global_third_party_index = GLOBAL_SNIPPETS_DIR / "third-party" / "index.yaml"

    # Load global snippets first, then selected project snippets.
    snippets: list[SnippetMeta] = []
    snippets.extend(
        _load_index(
            global_index,
            source_project="global",
            rewrite_project_prefix=False,
            project_root=global_root,
        )
    )
    if projects:
        seen_projects: set[str] = set()
        for project_name in projects:
            project_key = project_name.strip().lower()
            if not project_key or project_key in seen_projects:
                continue
            seen_projects.add(project_key)
            manifest_entry = manifest_projects.get(project_key)
            if not manifest_entry:
                continue
            index_path, manifest_root, canonical_name = manifest_entry
            snippets.extend(
                _load_index(
                    index_path,
                    source_project=canonical_name,
                    rewrite_project_prefix=True,
                    project_root=manifest_root,
                )
            )
    else:
        snippets.extend(
            _load_index(
                project_index,
                source_project=current_project_name,
                rewrite_project_prefix=False,
                project_root=project_root,
            )
        )

    # Build path-to-snippet mapping for baseline resolution
    snippets_by_path = {str(s.path): s for s in snippets}

    # Auto-enable third-party loading when snippet_ids reference them
    if snippet_ids and any(sid.startswith("third-party/") for sid in snippet_ids):
        include_third_party = True

    # Load third-party entries (separate from taxonomy, not filtered by areas)
    third_party_entries: list[ThirdPartyMeta] = []
    if include_third_party:
        third_party_entries.extend(_load_third_party_index(global_third_party_index))
        third_party_entries.extend(_load_third_party_index(project_third_party_index))

    # Use explicit domains if provided, otherwise load from project config
    if domains:
        domain_config = {d: project_root / "docs" for d in domains}
    else:
        domain_config = _load_project_domains(project_root)
    project_domain_roots = {d: p for d, p in domain_config.items() if p.exists()}
    if not project_domain_roots:
        project_domain_roots = {d: project_root / "docs" for d in domain_config.keys()}

    # Phase 2 cross-project retrieval: load requested project indexes on demand.
    if snippet_ids:
        domain_prefixes = {name.lower() for name in domain_config.keys()}
        prefixes_to_load: set[str] = set()
        for sid in snippet_ids:
            if _is_cross_project_snippet_id(sid, domain_prefixes=domain_prefixes):
                prefixes_to_load.add(sid.split("/", 1)[0].strip().lower())
        already_loaded = {snippet.source_project.lower() for snippet in snippets if snippet.source_project}
        for project_key in prefixes_to_load:
            if project_key in already_loaded:
                continue
            manifest_entry = manifest_projects.get(project_key)
            if not manifest_entry:
                continue
            index_path, manifest_root, canonical_name = manifest_entry
            loaded = _load_index(
                index_path,
                source_project=canonical_name,
                rewrite_project_prefix=True,
                project_root=manifest_root,
            )
            snippets.extend(loaded)
            for snippet in loaded:
                snippets_by_path[str(snippet.path)] = snippet

    requested_ids = {sid.strip() for sid in (snippet_ids or []) if sid.strip()}

    def _include_snippet(snippet: SnippetMeta) -> bool:
        resolved_role = (caller_role or "").strip().lower()
        if human_role and not resolved_role:
            resolved_role = human_role.strip().lower()
        if not resolved_role:
            resolved_role = "admin"
        if resolved_role != "admin" and snippet.visibility != "public":
            return False
        if global_snippets_root in snippet.path.parents:
            if snippet.snippet_id.startswith("general/"):
                return True
            return any(snippet.snippet_id.startswith(f"{domain}/") for domain in domain_config)
        if snippet.scope == "project":
            is_cross_project = (
                bool(snippet.source_project) and snippet.source_project.lower() != current_project_name.lower()
            )
            if requested_ids and snippet.snippet_id in requested_ids and is_cross_project:
                return True
            if projects and is_cross_project:
                return True
            return any(
                root in snippet.path.parents or root == snippet.path.parent for root in project_domain_roots.values()
            )
        return True

    # Track all loaded IDs before filtering to distinguish "unknown" from "access denied" in Phase 2
    all_loaded_ids = {s.snippet_id for s in snippets}
    snippets = [snippet for snippet in snippets if _include_snippet(snippet)]

    # Load baseline IDs if baseline_only mode is requested
    if baseline_only:
        global_baseline = GLOBAL_SNIPPETS_DIR / "baseline.md"
        project_baseline = project_root / "docs" / "project" / "baseline.md"
        baseline_ids: set[str] = set()
        baseline_ids.update(_load_baseline_ids(global_baseline, snippets_by_path, project_root=global_root))
        baseline_ids.update(_load_baseline_ids(project_baseline, snippets_by_path, project_root=project_root))
        snippets = [s for s in snippets if s.snippet_id in baseline_ids]

    areas_set = set(areas)
    if areas_set:
        snippets_for_selection = [s for s in snippets if s.snippet_type in areas_set]
    else:
        snippets_for_selection = list(snippets)

    if not snippet_ids:
        parts: list[str] = [
            "# PHASE 1: Snippet Index (IDs + descriptions)",
            "# Review the snippets below and select the IDs you need.",
            "",
        ]
        ordered = sorted(
            snippets_for_selection,
            key=lambda s: (_scope_rank(_output_scope(s, global_snippets_root=global_snippets_root)), s.snippet_id),
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
            description = snippet.description or ""
            parts.append(f"{snippet.snippet_id}: {description}".strip())

        # Include third-party entries (separate section, not filtered by areas)
        if third_party_entries:
            parts.append("")
            parts.append("# Third-party documentation (not part of taxonomy)")
            ordered_third_party = sorted(
                third_party_entries,
                key=lambda s: (_scope_rank(s.scope), s.snippet_id),
            )
            for entry in ordered_third_party:
                description = entry.description or ""
                parts.append(f"{entry.snippet_id}: {description}".strip())

        parts.extend(
            [
                "",
                "# ⚠️  IMPORTANT: Call teleclaude__get_context again with the snippet IDs of interest!",
            ]
        )
        return "\n".join(parts)

    # Build valid IDs from both taxonomy snippets and third-party entries
    valid_ids = {s.snippet_id for s in snippets}
    third_party_by_id = {e.snippet_id: e for e in third_party_entries}
    valid_ids.update(third_party_by_id.keys())

    # Separate unknown IDs from access-denied IDs
    denied_ids = [sid for sid in (snippet_ids or []) if sid not in valid_ids and sid in all_loaded_ids]
    unknown_ids = [sid for sid in (snippet_ids or []) if sid not in valid_ids and sid not in all_loaded_ids]
    if unknown_ids:
        return f"ERROR: Unknown snippet IDs: {', '.join(unknown_ids)}"

    # Separate taxonomy and third-party selections (exclude denied IDs)
    selected_ids = list(snippet_ids or [])
    allowed_ids = [sid for sid in selected_ids if sid not in denied_ids]
    taxonomy_ids = [sid for sid in allowed_ids if sid not in third_party_by_id]
    third_party_ids = [sid for sid in allowed_ids if sid in third_party_by_id]

    resolved = _resolve_requires(taxonomy_ids, snippets, global_snippets_root=global_snippets_root)
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
        parts.append(f"# Auto-included (required by the above): {', '.join(dep_ids)}")
    parts.append("")

    for snippet in resolved:
        try:
            raw = snippet.path.read_text(encoding="utf-8")
            root_path = snippet.project_root or project_root
            if global_snippets_root in snippet.path.parents:
                root_path = global_root
            content = _resolve_inline_refs(raw, snippet_path=snippet.path, root_path=root_path)
            _, body = _split_frontmatter(content)
            body = strip_required_reads_section(body)
        except Exception as exc:
            logger.exception("context_selector_read_failed", path=str(snippet.path), error=str(exc))
            continue
        domain = _domain_for_snippet(snippet, project_domains=project_domain_roots)
        scope = _output_scope(snippet, global_snippets_root=global_snippets_root)
        parts.append(
            "\n".join(
                [
                    "---",
                    f"id: {snippet.snippet_id}",
                    f"type: {snippet.snippet_type}",
                    f"domain: {domain}",
                    f"scope: {scope}",
                    f"description: {snippet.description}",
                    "---",
                ]
            ).strip()
        )
        parts.append(body.lstrip("\n"))

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
                _, body = _split_frontmatter(raw)
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
