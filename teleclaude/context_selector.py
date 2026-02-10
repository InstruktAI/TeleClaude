from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import yaml
from instrukt_ai_logging import get_logger

from teleclaude.config.loader import load_project_config
from teleclaude.docs_index import extract_required_reads
from teleclaude.paths import GLOBAL_SNIPPETS_DIR
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


def _load_index(index_path: Path) -> list[SnippetMeta]:
    if not index_path.exists():
        logger.warning("snippet_index_missing", path=str(index_path))
        return []

    try:
        payload = yaml.safe_load(index_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.exception("snippet_index_load_failed", path=str(index_path), error=str(exc))
        return []

    if not isinstance(payload, dict):
        return []

    project_root = payload.get("project_root")
    snippets = payload.get("snippets")
    if not isinstance(project_root, str) or not isinstance(snippets, list):
        return []

    root_path = Path(project_root).expanduser().resolve()
    entries: list[SnippetMeta] = []
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
        entries.append(
            SnippetMeta(
                snippet_id=snippet_id,
                description=description,
                snippet_type=snippet_type,
                scope=scope,
                path=path,
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
            if req_snippet and str(req_snippet.path) not in seen:
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
    test_agent: str | None = None,
    test_mode: str | None = None,
    test_request: str | None = None,
    test_csv_path: str | None = None,
) -> str:
    project_index = project_root / "docs" / "project" / "index.yaml"
    global_index = GLOBAL_SNIPPETS_DIR / "index.yaml"
    global_root = GLOBAL_SNIPPETS_DIR.parent.parent
    global_snippets_root = GLOBAL_SNIPPETS_DIR

    # Third-party indexes (separate from taxonomy)
    project_third_party_index = project_root / "docs" / "third-party" / "index.yaml"
    global_third_party_index = GLOBAL_SNIPPETS_DIR / "third-party" / "index.yaml"

    # Load global snippets first, then project snippets.
    snippets: list[SnippetMeta] = []
    snippets.extend(_load_index(global_index))
    snippets.extend(_load_index(project_index))

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

    def _include_snippet(snippet: SnippetMeta) -> bool:
        if global_snippets_root in snippet.path.parents:
            if snippet.snippet_id.startswith("general/"):
                return True
            return any(snippet.snippet_id.startswith(f"{domain}/") for domain in domain_config)
        if snippet.scope == "project":
            return any(
                root in snippet.path.parents or root == snippet.path.parent for root in project_domain_roots.values()
            )
        return True

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

    invalid_ids = [sid for sid in (snippet_ids or []) if sid not in valid_ids]
    if invalid_ids:
        return f"ERROR: Unknown snippet IDs: {', '.join(invalid_ids)}"

    # Separate taxonomy and third-party selections
    selected_ids = list(snippet_ids or [])
    taxonomy_ids = [sid for sid in selected_ids if sid not in third_party_by_id]
    third_party_ids = [sid for sid in selected_ids if sid in third_party_by_id]

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
            root_path = project_root
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

    return "\n".join(parts)
