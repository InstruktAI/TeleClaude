"""Snippet validation, inline ref helpers, and third-party doc validation."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator, Mapping
from pathlib import Path

import frontmatter

from teleclaude.constants import (
    SNIPPET_VISIBILITY_VALUES,
    TYPE_SUFFIX,
    RoadmapStatus,
)
from teleclaude.core.todos_db import todos_db_path
from teleclaude.paths import GLOBAL_SNIPPETS_DIR
from teleclaude.resource_validation._models import (
    _ARTIFACT_REF_ORDER,
    _CODE_FENCE_LINE,
    _H1_LINE,
    _H2_LINE,
    _HEADER_LINE,
    _HTML_COMMENT_LINE,
    _INLINE_CODE_SPAN,
    _INLINE_REF_LINE,
    _REQUIRED_READS_HEADER,
    _SCHEMA,
    _SEE_ALSO_HEADER,
    _SEE_ALSO_LIST_LINE,
    _SOURCES_HEADER,
    _as_str_list,
    _error,
    _first_out_of_order_ref,
)
from teleclaude.snippet_roots import is_excluded_snippet_path, iter_snippet_roots
from teleclaude.snippet_validation import (
    expected_snippet_id_for_path,
    is_companion,
    load_domains,
    validate_inline_ref_format,
    validate_snippet_id_format,
)

_MARKDOWN_LINK_RE = re.compile(r"^\[([^\]]+)\]\((https?://[^)]+)\)$")
INCLUDE_DIRECTIVE_RE = re.compile(r"<!--\s*@include:\s*(.+?\.md)\s*-->")
_THIRD_PARTY_TYPE = "third-party"
_THIRD_PARTY_INDEX_NAMES = frozenset({"index.md", "index.yaml"})
_ROADMAP_STATUS_VALUES = (
    RoadmapStatus.ACTIVE,
    RoadmapStatus.ICEBOX,
    RoadmapStatus.DELIVERED,
    RoadmapStatus.REMOVED,
)
_ROADMAP_STATUS_PRIORITY = {
    RoadmapStatus.REMOVED: -1,
    RoadmapStatus.DELIVERED: 0,
    RoadmapStatus.ACTIVE: 1,
    RoadmapStatus.ICEBOX: 1,
}


# ---------------------------------------------------------------------------
# Shared ref resolution
# ---------------------------------------------------------------------------


def resolve_ref_path(ref: str, *, root_path: Path, current_path: Path) -> Path | None:
    """Resolve an ``@`` reference to an absolute path.

    Handles absolute paths, ``~/`` expansion, ``docs/`` relative paths with
    project/global fallback, and paths relative to the referencing file.
    """
    if "://" in ref:
        return None
    candidate = Path(ref).expanduser()
    if not candidate.is_absolute():
        if str(candidate).startswith("docs/"):
            candidate = (root_path / candidate).resolve()
            if not candidate.exists():
                tail = Path(ref).relative_to("docs")
                project_candidate = (root_path / "docs" / "project" / tail).resolve()
                if project_candidate.exists():
                    candidate = project_candidate
                else:
                    global_candidate = (root_path / "docs" / "global" / tail).resolve()
                    if global_candidate.exists():
                        candidate = global_candidate
        else:
            candidate = (current_path.parent / candidate).resolve()
    else:
        candidate = candidate.resolve()
    return candidate


# ---------------------------------------------------------------------------
# Inline ref helpers
# ---------------------------------------------------------------------------


def iter_inline_refs(lines: list[str]) -> list[str]:
    """Extract ``@`` refs from lines, skipping code fences."""
    refs: list[str] = []
    in_code_block = False
    for line in lines:
        if _CODE_FENCE_LINE.match(line.strip()):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if not _INLINE_REF_LINE.match(line):
            continue
        ref = line.strip().lstrip("-").strip()
        refs.append(ref)
    return refs


def _get_allowed_ref_prefixes() -> tuple[str, ...]:
    home = str(Path.home())
    return f"@{home}/.teleclaude/docs/", "@~/.teleclaude/docs/", "@docs/"


def collect_inline_ref_errors(
    project_root: Path, snippet_path: Path, lines: list[str], *, domains: set[str]
) -> list[dict[str, str]]:
    """Validate inline ``@`` refs for format and existence."""
    errors: list[dict[str, str]] = []
    allowed_prefixes = _get_allowed_ref_prefixes()
    for ref in iter_inline_refs(lines):
        if not ref.startswith(allowed_prefixes):
            errors.append({"code": "snippet_invalid_inline_ref", "path": str(snippet_path), "ref": ref})
            continue
        format_error = validate_inline_ref_format(ref, domains=domains)
        if format_error:
            errors.append(
                {
                    "code": "snippet_inline_ref_format_invalid",
                    "path": str(snippet_path),
                    "ref": ref,
                    "reason": format_error,
                }
            )
            continue
        resolved = _resolve_snippet_ref(project_root, snippet_path, ref)
        if resolved is None:
            errors.append({"code": "snippet_invalid_inline_ref", "path": str(snippet_path), "ref": ref})
            continue
        if not resolved.exists():
            errors.append(
                {
                    "code": "snippet_inline_ref_missing",
                    "path": str(snippet_path),
                    "ref": ref,
                    "resolved": str(resolved),
                }
            )
            continue
        if not resolved.is_file():
            errors.append(
                {
                    "code": "snippet_inline_ref_not_file",
                    "path": str(snippet_path),
                    "ref": ref,
                    "resolved": str(resolved),
                }
            )
    return errors


def _resolve_snippet_ref(project_root: Path, snippet_path: Path, ref: str) -> Path | None:  # pylint: disable=unused-argument
    if not ref.startswith("@"):
        return None
    target = ref[1:]
    if target.startswith("~"):
        return Path(target).expanduser()
    if target.startswith("./") or target.startswith("/"):
        return Path(target)
    if target.startswith("../"):
        raise NotImplementedError("Relative refs with .. not supported")
    return (project_root / target).resolve()


# ---------------------------------------------------------------------------
# Snippet validation
# ---------------------------------------------------------------------------


def _normalize_section_title(title: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", title).strip().lower()
    return re.sub(r"\s+", " ", cleaned)


def _infer_type_from_path(file_path: Path) -> str | None:
    parts = list(file_path.parts)
    try:
        baseline_idx = parts.index("baseline")
    except ValueError:
        return None
    if baseline_idx + 1 >= len(parts):
        return None
    folder = parts[baseline_idx + 1]
    return folder if folder in TYPE_SUFFIX else None


def _snippet_type_for_validation(path: Path, meta: Mapping[str, object]) -> str | None:
    raw_type = meta.get("type")
    if isinstance(raw_type, str):
        return raw_type
    return _infer_type_from_path(path)


def _validate_visibility(path: Path, meta: Mapping[str, object]) -> None:
    raw_visibility = meta.get("visibility")
    if raw_visibility is None:
        return
    if not isinstance(raw_visibility, str) or raw_visibility not in SNIPPET_VISIBILITY_VALUES:
        _error("snippet_invalid_visibility_value", path=str(path), value=str(raw_visibility))


def _validate_activation_trigger(path: Path, meta: Mapping[str, object], *, snippet_type: str | None) -> None:
    activation_trigger = meta.get("activation_trigger")
    if activation_trigger is None:
        return
    if snippet_type != "procedure":
        _error("snippet_activation_trigger_invalid_type", path=str(path))
        return
    if not isinstance(activation_trigger, str):
        _error("snippet_activation_trigger_invalid_value", path=str(path))
        return
    if not activation_trigger.strip():
        _error("snippet_activation_trigger_empty", path=str(path))


def build_roadmap_status_map(project_root: Path) -> dict[str, str]:
    """Read roadmap slug status once for snippet validation/reconciliation.

    Falls back to the canonical state root (main repo) when invoked from a
    git worktree where ``.teleclaude/todos.db`` is not present.
    """
    db_path = todos_db_path(project_root)
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    try:
        # A real todo exists in ``todo_state``; the legacy ``roadmap`` table only
        # carries the delivered/removed status (until ``v2-workflow-drop-roadmap``
        # migrates it). Join so orphaned roadmap rows with no real todo are excluded
        # — otherwise a phantom slug would read as a live deliverer.
        rows = conn.execute(
            "SELECT r.slug, r.status FROM roadmap r "  # guard: raw-sql
            "JOIN todo_state ts ON ts.slug = r.slug "
            "WHERE r.status IN (?, ?, ?, ?)",
            _ROADMAP_STATUS_VALUES,
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return {}
        raise
    finally:
        conn.close()

    status_map: dict[str, str] = {}
    for slug, raw_status in rows:
        if not isinstance(slug, str) or not isinstance(raw_status, str):
            continue
        try:
            status = RoadmapStatus(raw_status)
        except ValueError:
            continue
        if status not in _ROADMAP_STATUS_VALUES:
            continue
        current_raw = status_map.get(slug)
        if current_raw is None:
            status_map[slug] = status.value
            continue
        current = RoadmapStatus(current_raw)
        if _ROADMAP_STATUS_PRIORITY[status] > _ROADMAP_STATUS_PRIORITY[current]:
            status_map[slug] = status.value
    return status_map


def _validate_delivered_by(
    path: Path,
    meta: Mapping[str, object],
) -> None:
    raw_delivered_by = meta.get("delivered_by")
    if raw_delivered_by is None:
        return
    delivered_by = _as_str_list(raw_delivered_by)
    if not delivered_by:
        _error("snippet_delivered_by_invalid_shape", path=str(path))


_LIVE_ROADMAP_STATUSES = frozenset({RoadmapStatus.ACTIVE.value, RoadmapStatus.ICEBOX.value})


def _validate_delivered_by_roadmap(
    path: Path,
    meta: Mapping[str, object],
    roadmap_status_map: Mapping[str, str],
) -> None:
    """Flag any delivered_by slug that is not a live (active/icebox) todo.

    A valid pending marker names an in-flight todo. A slug resolving to a
    delivered/removed todo should have been cleared on delivery; one resolving to
    nothing is a typo or a deleted todo. Both are anomalies — not legacy to tolerate
    — so they fail validation and must be removed.
    """
    delivered_by = _as_str_list(meta.get("delivered_by"))
    for slug in delivered_by:
        status = roadmap_status_map.get(slug)
        if status in _LIVE_ROADMAP_STATUSES:
            continue
        reason = "no such todo (typo or deleted)" if status is None else f"todo is {status}, not in flight"
        _error("snippet_delivered_by_invalid_slug", path=str(path), slug=slug, reason=reason)


def validate_snippet(
    path: Path,
    content: str,
    project_root: Path,
    *,
    domains: set[str],
    roadmap_status_map: Mapping[str, str] | None = None,
) -> None:
    """Validate a single doc snippet. Collects validation findings via ``_error``.

    When ``roadmap_status_map`` is provided, delivered_by slugs are also checked
    against the live roadmap (existence + in-flight status); when ``None`` the
    snippet is validated for shape only (roadmap-agnostic callers).
    """
    if _is_third_party_doc(path, project_root):
        validate_third_party_doc(path, content, project_root)
        return
    if (path.name == "index.md" and "baseline" in path.parts) or (
        path.name.startswith("baseline")
        and path.name.endswith(".md")
        and (path.parent.name in ("global", "project") or path.parent.parent.name in ("global", "project"))
    ):
        _validate_baseline_index(path, content, project_root, domains=domains)
        return
    has_frontmatter = content.lstrip().startswith("---")
    if has_frontmatter:
        try:
            post = frontmatter.loads(content)
            meta: Mapping[str, object] = post.metadata or {}
            body = post.content
        except Exception:  # pylint: disable=broad-exception-caught
            meta = {}
            body = content
    else:
        meta = {}
        body = content
    lines = body.splitlines()

    # A companion `<stem>.<slug>.md` is the full next version of `<stem>.md` and
    # deliberately shares the parent's id; validate it as a full snippet but exempt
    # the id↔path checks. See documentation-first-development section 10.
    companion = is_companion(path)
    expected_id, path_error = expected_snippet_id_for_path(path, project_root=project_root, domains=domains)
    if path_error and not companion:
        _error("snippet_invalid_path", path=str(path), reason=path_error)

    parsed_id = None
    snippet_id = meta.get("id")
    if isinstance(snippet_id, str):
        parsed_id, id_error = validate_snippet_id_format(snippet_id, domains=domains)
        if id_error:
            _error(
                "snippet_invalid_id_format",
                path=str(path),
                reason=id_error,
                snippet_id=snippet_id,
            )
    if expected_id and parsed_id and parsed_id.value() != expected_id and not companion:
        _error(
            "snippet_id_path_mismatch",
            path=str(path),
            expected_id=expected_id,
            snippet_id=parsed_id.value(),
        )

    _validate_visibility(path, meta)
    snippet_type = _snippet_type_for_validation(path, meta)
    _validate_activation_trigger(path, meta, snippet_type=snippet_type)
    _validate_delivered_by(path, meta)
    if roadmap_status_map is not None:
        _validate_delivered_by_roadmap(path, meta, roadmap_status_map)
    _validate_snippet_structure(path, lines, meta, has_frontmatter, domains=domains)
    _validate_snippet_refs(path, lines, project_root, domains=domains)
    _validate_snippet_sections(path, lines, meta, domains=domains)


def _validate_baseline_index(path: Path, content: str, project_root: Path, *, domains: set[str]) -> None:
    if content.lstrip().startswith("---"):
        try:
            post = frontmatter.loads(content)
            content = post.content
        except Exception:  # pylint: disable=broad-exception-caught
            pass
    lines = [line for line in content.splitlines() if line.strip()]
    ref_lines = [line for line in lines if line.startswith("@")]
    for line in lines:
        if not line.startswith("@"):
            # Only report if the file also contains @ refs — mixed content is suspicious.
            # A pure-instruction baseline file (no @ lines) is intentionally prose-only.
            if ref_lines:
                _error("snippet_baseline_index_invalid_line", path=str(path), line=line)
    bad_ref = _first_out_of_order_ref(ref_lines)
    if bad_ref is not None:
        _error(
            "snippet_baseline_index_out_of_order",
            path=str(path),
            line=bad_ref,
            expected_order=" → ".join(_ARTIFACT_REF_ORDER),
        )
    for error in collect_inline_ref_errors(project_root, path, lines, domains=domains):
        _error(error["code"], **{k: v for k, v in error.items() if k != "code"})


def _validate_snippet_structure(  # pylint: disable=too-many-branches,unused-argument
    path: Path,
    lines: list[str],
    meta: Mapping[str, object],
    has_frontmatter: bool,
    *,
    domains: set[str],
) -> None:
    if _SCHEMA["global_"].get("require_h1", True):
        first_non_empty = next((line for line in lines if line.strip()), "")
        if not _H1_LINE.match(first_non_empty):
            _error("snippet_missing_h1", path=str(path))
        if _SCHEMA["global_"].get("require_h1_first", True):
            if first_non_empty and not _H1_LINE.match(first_non_empty):
                _error("snippet_h1_not_first", path=str(path))
    if not any(_H2_LINE.match(line) for line in lines):
        _error("snippet_missing_h2", path=str(path))

    required_reads_found = False
    required_reads_header_idx = None
    required_reads_text_header = False
    sources_found = False
    sources_header_idx = None
    for idx, line in enumerate(lines):
        if _REQUIRED_READS_HEADER.match(line):
            required_reads_found = True
            required_reads_header_idx = idx
            break
    for line in lines:
        if line.strip().lower() == "required reads:":
            required_reads_text_header = True
            break
    for idx, line in enumerate(lines):
        if _SOURCES_HEADER.match(line):
            sources_found = True
            sources_header_idx = idx
            break
    if _SCHEMA["global_"].get("require_required_reads", True):
        if not required_reads_found:
            _error("snippet_required_reads_missing", path=str(path))
        if required_reads_text_header:
            _error("snippet_required_reads_text_header", path=str(path))
        if required_reads_found and required_reads_header_idx is not None:
            if not lines[required_reads_header_idx].startswith("## "):
                _error("snippet_required_reads_header_level", path=str(path))
            h2_indices = [i for i, line in enumerate(lines) if _H2_LINE.match(line)]
            if h2_indices and h2_indices[0] != required_reads_header_idx:
                _error("snippet_required_reads_not_first_h2", path=str(path))

    if sources_found and sources_header_idx is not None:
        if not lines[sources_header_idx].startswith("## "):
            _error("snippet_sources_header_level", path=str(path))


def _is_global_doc(path: Path) -> bool:
    return "global" in path.parts


def _global_docs_prefixes() -> tuple[str, str]:
    home_docs = str(GLOBAL_SNIPPETS_DIR)
    return "~/.teleclaude/docs/", f"{home_docs}/"


def _resolve_see_also_ref(ref: str, project_root: Path) -> Path | None:
    """Resolve a See Also soft reference to an absolute path for existence check."""
    if ref.startswith("~"):
        expanded = str(Path(ref).expanduser())
        home_prefix = str(GLOBAL_SNIPPETS_DIR) + "/"
        if expanded.startswith(home_prefix):
            tail = expanded[len(home_prefix) :]
            return (project_root / "docs" / "global" / tail).resolve()
        return Path(expanded).resolve()
    _, absolute_prefix = _global_docs_prefixes()
    if ref.startswith(absolute_prefix):
        tail = ref[len(absolute_prefix) :]
        return (project_root / "docs" / "global" / tail).resolve()
    if ref.startswith("docs/"):
        return (project_root / ref).resolve()
    return None


def _validate_see_also_ref(ref_line: str, path: Path, project_root: Path) -> None:
    """Validate a single list item inside a ``## See Also`` section."""
    raw = ref_line.split("\u2014")[0].split(" -- ")[0].strip()
    if not raw:
        return
    if raw.startswith("http://") or raw.startswith("https://"):
        return

    is_global = _is_global_doc(path)
    tilde_prefix, absolute_prefix = _global_docs_prefixes()

    if is_global:
        if not raw.startswith((tilde_prefix, absolute_prefix)):
            _error(
                "snippet_see_also_bad_prefix",
                path=str(path),
                ref=raw,
                expected="~/.teleclaude/docs/...",
            )
            return
    else:
        if not raw.startswith("docs/") and not raw.startswith((tilde_prefix, absolute_prefix)):
            _error(
                "snippet_see_also_bad_prefix",
                path=str(path),
                ref=raw,
                expected="docs/... or ~/.teleclaude/docs/...",
            )
            return

    if not raw.endswith(".md"):
        _error("snippet_see_also_missing_extension", path=str(path), ref=raw)
        return

    resolved = _resolve_see_also_ref(raw, project_root)
    if resolved is None:
        _error("snippet_see_also_unresolvable", path=str(path), ref=raw)
        return
    if not resolved.exists():
        _error("snippet_see_also_missing", path=str(path), ref=raw, resolved=str(resolved))


def _validate_snippet_refs(path: Path, lines: list[str], project_root: Path, *, domains: set[str]) -> None:  # pylint: disable=too-many-branches
    in_required_reads = False
    in_see_also = False
    in_code_block = False
    for line in lines:
        if _CODE_FENCE_LINE.match(line.strip()):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if _REQUIRED_READS_HEADER.match(line):
            in_required_reads = True
            in_see_also = False
            continue
        if _SEE_ALSO_HEADER.match(line):
            in_required_reads = False
            in_see_also = True
            continue
        if _H2_LINE.match(line):
            in_required_reads = False
            in_see_also = False
            continue
        if _HTML_COMMENT_LINE.match(line):
            continue
        line_without_inline = _INLINE_CODE_SPAN.sub("", line)
        if "@" in line_without_inline:
            if in_see_also:
                _error("snippet_see_also_inline_ref", path=str(path), line=line.strip())
            elif not in_required_reads:
                _error("snippet_required_reads_outside_section", path=str(path), line=line.strip())
        if in_see_also:
            m = _SEE_ALSO_LIST_LINE.match(line)
            if m:
                _validate_see_also_ref(m.group(1), path, project_root)

    for error in collect_inline_ref_errors(project_root, path, lines, domains=domains):
        _error(error["code"], **{k: v for k, v in error.items() if k != "code"})


def _validate_snippet_sections(  # pylint: disable=too-many-locals,too-many-branches,unused-argument
    path: Path,
    lines: list[str],
    meta: Mapping[str, object],
    *,
    domains: set[str],
) -> None:
    h2_titles: list[str] = []
    in_code_block = False
    for line in lines:
        if _CODE_FENCE_LINE.match(line.strip()):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        if _H2_LINE.match(line):
            h2_titles.append(line.lstrip("#").strip())
    normalized_titles = [_normalize_section_title(t) for t in h2_titles]

    if "see also" in normalized_titles:
        last_h2 = normalized_titles[-1] if normalized_titles else ""
        if last_h2 != "see also":
            _error("snippet_see_also_not_last", path=str(path))

    if "baseline" not in path.parts:
        has_frontmatter = any(True for _ in [meta] if meta)
        if not has_frontmatter or not any(isinstance(meta.get(f), str) for f in ("id",)):
            pass  # handled elsewhere
        for field in ("id", "type", "scope", "description"):
            if not isinstance(meta.get(field), str) or not meta.get(field):
                _error("snippet_missing_frontmatter_field", path=str(path), field=field)

    visibility_val = meta.get("visibility")
    if visibility_val is not None:
        if not isinstance(visibility_val, str) or visibility_val not in SNIPPET_VISIBILITY_VALUES:
            _error("snippet_invalid_visibility_value", path=str(path), value=str(visibility_val))

    snippet_type = meta.get("type") if isinstance(meta.get("type"), str) else None
    if not snippet_type:
        snippet_type = _infer_type_from_path(path)
    if snippet_type:
        type_key = str(snippet_type).lower()
        section_rules = _SCHEMA["sections"].get(type_key, {})  # type: ignore[var-annotated]
        required = [_normalize_section_title(s) for s in section_rules.get("required", [])]
        allowed = [_normalize_section_title(s) for s in section_rules.get("allowed", [])]
        for req in required:
            if req not in normalized_titles:
                _error("snippet_missing_required_section", path=str(path), section=req)
        for title in normalized_titles:
            if title in ("required reads", "see also", "sources"):
                continue
            if title not in allowed:
                _error("snippet_unknown_section", path=str(path), section=title)


# ---------------------------------------------------------------------------
# Third-party validation
# ---------------------------------------------------------------------------


def _is_third_party_doc(path: Path, project_root: Path) -> bool:
    try:
        rel = path.resolve().relative_to(project_root.resolve())
    except (OSError, ValueError):
        return False
    return len(rel.parts) >= 3 and rel.parts[0] == "docs" and rel.parts[1] == _THIRD_PARTY_TYPE


def _expected_third_party_id(path: Path, project_root: Path) -> str | None:
    if path.name in _THIRD_PARTY_INDEX_NAMES:
        return None
    try:
        rel = path.resolve().relative_to((project_root / "docs" / _THIRD_PARTY_TYPE).resolve())
    except (OSError, ValueError):
        return None
    rel_no_suffix = rel.with_suffix("")
    return f"{_THIRD_PARTY_TYPE}/{rel_no_suffix.as_posix()}"


def _extract_sources_section(lines: list[str]) -> list[str]:
    in_sources = False
    sources: list[str] = []
    for line in lines:
        if _SOURCES_HEADER.match(line):
            in_sources = True
            continue
        if in_sources:
            if _HEADER_LINE.match(line):
                break
            stripped = line.strip()
            if stripped.startswith("- "):
                sources.append(stripped[2:].strip())
    return sources


def _is_context7_id(value: str) -> bool:
    return bool(re.match(r"^/[a-zA-Z0-9_-]+/[a-zA-Z0-9_.-]+$", value))


def _is_web_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _extract_markdown_link_url(value: str) -> str | None:
    """Extract URL from a markdown link like [text](https://...)."""
    m = _MARKDOWN_LINK_RE.match(value)
    return m.group(2) if m else None


def _validate_third_party_frontmatter(path: Path, meta: Mapping[str, object], project_root: Path) -> None:
    for field in ("id", "type", "scope", "description"):
        if not isinstance(meta.get(field), str) or not meta.get(field):
            _error("snippet_missing_frontmatter_field", path=str(path), field=field)

    expected_id = _expected_third_party_id(path, project_root)
    raw_id = meta.get("id")
    if expected_id and isinstance(raw_id, str) and raw_id != expected_id:
        _error("third_party_id_path_mismatch", path=str(path), expected_id=expected_id, snippet_id=raw_id)

    raw_type = meta.get("type")
    if isinstance(raw_type, str) and raw_type != _THIRD_PARTY_TYPE:
        _error("third_party_invalid_type", path=str(path), value=raw_type)

    raw_scope = meta.get("scope")
    if isinstance(raw_scope, str) and raw_scope not in {"project", "global"}:
        _error("third_party_invalid_scope", path=str(path), value=raw_scope)


def _validate_third_party_sources(path: Path, lines: list[str]) -> None:
    sources = _extract_sources_section(lines)
    for source in sources:
        if _is_context7_id(source):
            continue
        url = source
        md_url = _extract_markdown_link_url(source)
        if md_url:
            url = md_url
        if _is_web_url(url):
            continue
        _error("third_party_source_invalid", path=str(path), source=source)


def validate_third_party_doc(path: Path, content: str, project_root: Path) -> None:
    """Validate one third-party doc snippet."""
    if path.name in _THIRD_PARTY_INDEX_NAMES:
        return
    if content.lstrip().startswith("---"):
        try:
            post = frontmatter.loads(content)
            meta: Mapping[str, object] = post.metadata or {}
            body = post.content
        except Exception:  # pylint: disable=broad-exception-caught
            meta = {}
            body = content
    else:
        meta = {}
        body = content

    lines = body.splitlines()
    first_non_empty = next((line for line in lines if line.strip()), "")
    if not _H1_LINE.match(first_non_empty):
        _error("snippet_missing_h1", path=str(path))
    if not any(_H2_LINE.match(line) for line in lines):
        _error("snippet_missing_h2", path=str(path))

    _validate_third_party_frontmatter(path, meta, project_root)
    _validate_third_party_sources(path, lines)


def validate_third_party_docs(project_root: Path) -> None:
    """Validate third-party doc frontmatter and sources."""
    third_party_root = project_root / "docs" / "third-party"
    if not third_party_root.exists():
        return
    for path in sorted(third_party_root.rglob("*.md")):
        if path.name in _THIRD_PARTY_INDEX_NAMES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            _error("third_party_read_failed", path=str(path), error=str(exc))
            continue
        validate_third_party_doc(path, text, project_root)


# ---------------------------------------------------------------------------
# Snippet entry points
# ---------------------------------------------------------------------------


def _iter_snippet_roots(project_root: Path) -> list[Path]:
    """Find all snippet root directories under the project."""
    return iter_snippet_roots(project_root)


_BASELINE_REF_RE = re.compile(r"@([\w./~\-]+\.md)")


def _domain_baseline_ids(domain: str, project_root: Path) -> set[str]:
    """Snippet ids inflated by a domain's resident baseline manifest."""
    baseline = project_root / "docs" / "global" / domain / "baseline.md"
    if not baseline.exists():
        return set()
    ids: set[str] = set()
    for ref in _BASELINE_REF_RE.findall(baseline.read_text(encoding="utf-8")):
        resolved = resolve_ref_path(ref, root_path=project_root, current_path=baseline)
        if resolved and resolved.exists():
            snippet_id = frontmatter.loads(resolved.read_text(encoding="utf-8")).metadata.get("id")
            if isinstance(snippet_id, str) and snippet_id:
                ids.add(snippet_id)
    return ids


def _iter_reachable_refs(start: Path, project_root: Path, seen: set[Path]) -> Iterator[tuple[str, Path]]:
    """Yield (snippet_id, containing_file) for every snippet transitively @-referenced from start."""
    try:
        text = start.read_text(encoding="utf-8")
    except OSError:
        return
    for ref in _BASELINE_REF_RE.findall(text):
        resolved = resolve_ref_path(ref, root_path=project_root, current_path=start)
        if not resolved or not resolved.exists() or resolved in seen:
            continue
        seen.add(resolved)
        try:
            snippet_id = frontmatter.loads(resolved.read_text(encoding="utf-8")).metadata.get("id")
        except OSError:
            continue
        if isinstance(snippet_id, str) and snippet_id:
            yield snippet_id, start
        yield from _iter_reachable_refs(resolved, project_root, seen)


def _validate_baseline_dedup(project_root: Path) -> None:
    """Fail when a procedure that injects its domain baseline also re-includes baseline content.

    A procedure declaring ``needs_domain_baseline: true`` has its domain baseline
    injected at SessionStart. If that procedure — directly or transitively through
    its required reads — re-includes a snippet already in that baseline, the content
    is delivered twice. The fix is to drop the redundant required read, not to rely
    on silent build-time deduplication.
    """
    for snippets_root in _iter_snippet_roots(project_root):
        for path in sorted(snippets_root.rglob("*.md")):
            if path.name == "index.yaml" or is_excluded_snippet_path(path, snippets_root):
                continue
            try:
                meta = frontmatter.loads(path.read_text(encoding="utf-8")).metadata
            except OSError:
                continue
            flag = meta.get("needs_domain_baseline")
            if not (flag is True or (isinstance(flag, str) and flag.strip().lower() == "true")):
                continue
            domain = meta.get("domain")
            if not isinstance(domain, str) or not domain:
                continue
            baseline_ids = _domain_baseline_ids(domain, project_root)
            for snippet_id, container in _iter_reachable_refs(path, project_root, set()):
                if snippet_id in baseline_ids:
                    _error("baseline_dedup_violation", path=str(container), snippet_id=snippet_id, domain=domain)


def _resolve_roadmap_status_map(project_root: Path) -> dict[str, str] | None:
    """Load the roadmap slug→status map, or ``None`` when no todos DB is reachable.

    Returning ``None`` (DB genuinely absent — fresh clone, CI without state) skips
    the delivered_by roadmap-validity check rather than flagging every slug as
    missing. An empty map with a present DB is a real empty roadmap and still runs.
    """
    if todos_db_path(project_root).exists():
        return build_roadmap_status_map(project_root)
    return None


def validate_all_snippets(project_root: Path) -> None:
    """Validate all doc snippets under the project. Collects validation findings."""
    domains = load_domains(project_root)
    roadmap_status_map = _resolve_roadmap_status_map(project_root)
    snippet_roots = _iter_snippet_roots(project_root)
    for snippets_root in snippet_roots:
        try:
            rel_path = snippets_root.relative_to(project_root)
            include_baseline = str(rel_path) in ("docs/global", "agents/docs")
        except ValueError:
            include_baseline = False
        for path in sorted(snippets_root.rglob("*.md")):
            if path.name == "index.yaml":
                continue
            if is_excluded_snippet_path(path, snippets_root):
                continue
            if not include_baseline and "baseline" in str(path):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:
                _error("snippet_read_failed", path=str(path), error=str(exc))
                continue
            validate_snippet(path, text, project_root, domains=domains, roadmap_status_map=roadmap_status_map)
    _validate_baseline_dedup(project_root)
    validate_third_party_docs(project_root)
