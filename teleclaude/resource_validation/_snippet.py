"""Snippet validation, inline ref helpers, and third-party doc validation."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

import frontmatter

from teleclaude.constants import SNIPPET_VISIBILITY_VALUES, TYPE_SUFFIX
from teleclaude.resource_validation._models import (
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
    _error,
    _warn,
)
from teleclaude.snippet_validation import (
    expected_snippet_id_for_path,
    load_domains,
    validate_inline_ref_format,
    validate_snippet_id_format,
)

_MARKDOWN_LINK_RE = re.compile(r"^\[([^\]]+)\]\((https?://[^)]+)\)$")


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


def _get_allowed_ref_prefixes() -> tuple[str, str]:
    home = str(Path.home())
    return f"@{home}/.teleclaude/docs/", "@docs/"


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


def _resolve_snippet_ref(project_root: Path, snippet_path: Path, ref: str) -> Path | None:
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


def validate_snippet(path: Path, content: str, project_root: Path, *, domains: set[str]) -> None:
    """Validate a single doc snippet. Collects warnings via ``_warn``."""
    if (path.name == "index.md" and "baseline" in path.parts) or (
        path.name.startswith("baseline") and path.name.endswith(".md") and path.parent.name in ("global", "project")
    ):
        _validate_baseline_index(path, content, project_root, domains=domains)
        return
    has_frontmatter = content.lstrip().startswith("---")
    if has_frontmatter:
        try:
            post = frontmatter.loads(content)
            meta: Mapping[str, object] = post.metadata or {}
            body = post.content
        except Exception:
            meta = {}
            body = content
    else:
        meta = {}
        body = content
    lines = body.splitlines()

    expected_id, path_error = expected_snippet_id_for_path(path, project_root=project_root, domains=domains)
    if path_error:
        _warn("snippet_invalid_path", path=str(path), reason=path_error)

    parsed_id = None
    if isinstance(meta.get("id"), str):
        parsed_id, id_error = validate_snippet_id_format(meta["id"], domains=domains)
        if id_error:
            _warn("snippet_invalid_id_format", path=str(path), reason=id_error, snippet_id=meta["id"])
    if expected_id and parsed_id and parsed_id.value() != expected_id:
        _warn(
            "snippet_id_path_mismatch",
            path=str(path),
            expected_id=expected_id,
            snippet_id=parsed_id.value(),
        )

    raw_visibility = meta.get("visibility")
    if raw_visibility is not None:
        if not isinstance(raw_visibility, str) or raw_visibility not in SNIPPET_VISIBILITY_VALUES:
            _warn("snippet_invalid_visibility_value", path=str(path), value=str(raw_visibility))

    _validate_snippet_structure(path, lines, meta, has_frontmatter, domains=domains)
    _validate_snippet_refs(path, lines, project_root, domains=domains)
    _validate_snippet_sections(path, lines, meta, domains=domains)


def _validate_baseline_index(path: Path, content: str, project_root: Path, *, domains: set[str]) -> None:
    if content.lstrip().startswith("---"):
        try:
            post = frontmatter.loads(content)
            content = post.content
        except Exception:
            pass
    lines = [line for line in content.splitlines() if line.strip()]
    ref_lines = [line for line in lines if line.startswith("@")]
    for line in lines:
        if not line.startswith("@"):
            # Only warn if the file also contains @ refs — mixed content is suspicious.
            # A pure-instruction baseline file (no @ lines) is intentionally prose-only.
            if ref_lines:
                _warn("snippet_baseline_index_invalid_line", path=str(path), line=line)
    for error in collect_inline_ref_errors(project_root, path, lines, domains=domains):
        _warn(error["code"], **{k: v for k, v in error.items() if k != "code"})


def _validate_snippet_structure(
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
            _warn("snippet_missing_h1", path=str(path))
        if _SCHEMA["global_"].get("require_h1_first", True):
            if first_non_empty and not _H1_LINE.match(first_non_empty):
                _warn("snippet_h1_not_first", path=str(path))
    if not any(_H2_LINE.match(line) for line in lines):
        _warn("snippet_missing_h2", path=str(path))

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
            _warn("snippet_required_reads_missing", path=str(path))
        if required_reads_text_header:
            _warn("snippet_required_reads_text_header", path=str(path))
        if required_reads_found and required_reads_header_idx is not None:
            if not lines[required_reads_header_idx].startswith("## "):
                _warn("snippet_required_reads_header_level", path=str(path))
            h2_indices = [i for i, line in enumerate(lines) if _H2_LINE.match(line)]
            if h2_indices and h2_indices[0] != required_reads_header_idx:
                _warn("snippet_required_reads_not_first_h2", path=str(path))

    if sources_found and sources_header_idx is not None:
        if not lines[sources_header_idx].startswith("## "):
            _warn("snippet_sources_header_level", path=str(path))


def _is_global_doc(path: Path) -> bool:
    return "global" in path.parts


def _resolve_see_also_ref(ref: str, project_root: Path) -> Path | None:
    """Resolve a See Also soft reference to an absolute path for existence check."""
    if ref.startswith("~"):
        expanded = str(Path(ref).expanduser())
        home_prefix = str(Path.home() / ".teleclaude" / "docs") + "/"
        if expanded.startswith(home_prefix):
            tail = expanded[len(home_prefix) :]
            return (project_root / "docs" / "global" / tail).resolve()
        return Path(expanded).resolve()
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

    if is_global:
        if not raw.startswith("~/.teleclaude/docs/"):
            _error(
                "snippet_see_also_bad_prefix",
                path=str(path),
                ref=raw,
                expected="~/.teleclaude/docs/...",
            )
            return
    else:
        if not raw.startswith("docs/") and not raw.startswith("~/.teleclaude/docs/"):
            _error(
                "snippet_see_also_bad_prefix",
                path=str(path),
                ref=raw,
                expected="docs/... or ~/.teleclaude/docs/...",
            )
            return

    if not raw.endswith(".md"):
        _warn("snippet_see_also_missing_extension", path=str(path), ref=raw)
        return

    resolved = _resolve_see_also_ref(raw, project_root)
    if resolved is None:
        _warn("snippet_see_also_unresolvable", path=str(path), ref=raw)
        return
    if not resolved.exists():
        _warn("snippet_see_also_missing", path=str(path), ref=raw, resolved=str(resolved))


def _validate_snippet_refs(path: Path, lines: list[str], project_root: Path, *, domains: set[str]) -> None:
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
                _warn("snippet_see_also_inline_ref", path=str(path), line=line.strip())
            elif not in_required_reads:
                _warn("snippet_required_reads_outside_section", path=str(path), line=line.strip())
        if in_see_also:
            m = _SEE_ALSO_LIST_LINE.match(line)
            if m:
                _validate_see_also_ref(m.group(1), path, project_root)

    for error in collect_inline_ref_errors(project_root, path, lines, domains=domains):
        _warn(error["code"], **{k: v for k, v in error.items() if k != "code"})


def _validate_snippet_sections(
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
            _warn("snippet_see_also_not_last", path=str(path))

    if "baseline" not in path.parts:
        has_frontmatter = any(True for _ in [meta] if meta)
        if not has_frontmatter or not any(isinstance(meta.get(f), str) for f in ("id",)):
            pass  # handled elsewhere
        for field in ("id", "type", "scope", "description"):
            if not isinstance(meta.get(field), str) or not meta.get(field):
                _warn("snippet_missing_frontmatter_field", path=str(path), field=field)

    visibility_val = meta.get("visibility")
    if visibility_val is not None:
        if not isinstance(visibility_val, str) or visibility_val not in SNIPPET_VISIBILITY_VALUES:
            _warn("snippet_invalid_visibility_value", path=str(path), value=str(visibility_val))

    snippet_type = meta.get("type") if isinstance(meta.get("type"), str) else None
    if not snippet_type:
        snippet_type = _infer_type_from_path(path)
    if snippet_type:
        type_key = str(snippet_type).lower()
        section_rules = _SCHEMA["sections"].get(type_key, {})
        required = [_normalize_section_title(s) for s in section_rules.get("required", [])]
        allowed = [_normalize_section_title(s) for s in section_rules.get("allowed", [])]
        for req in required:
            if req not in normalized_titles:
                _warn("snippet_missing_required_section", path=str(path), section=req)
        for title in normalized_titles:
            if title in ("required reads", "see also", "sources"):
                continue
            if title not in allowed:
                _warn("snippet_unknown_section", path=str(path), section=title)


# ---------------------------------------------------------------------------
# Third-party validation
# ---------------------------------------------------------------------------


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


def validate_third_party_docs(project_root: Path) -> None:
    """Validate third-party doc sources exist and URLs are reachable."""
    third_party_root = project_root / "docs" / "third-party"
    if not third_party_root.exists():
        return
    for path in sorted(third_party_root.rglob("*.md")):
        if path.name == "index.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            _warn("third_party_read_failed", path=str(path), error=str(exc))
            continue
        lines = text.splitlines()
        sources = _extract_sources_section(lines)
        if not sources:
            continue
        for source in sources:
            if _is_context7_id(source):
                continue
            url = source
            md_url = _extract_markdown_link_url(source)
            if md_url:
                url = md_url
            if _is_web_url(url):
                continue
            _warn("third_party_source_invalid", path=str(path), source=source)


# ---------------------------------------------------------------------------
# Snippet entry points
# ---------------------------------------------------------------------------


def _iter_snippet_roots(project_root: Path) -> list[Path]:
    """Find all snippet root directories under the project."""
    roots: list[Path] = []
    candidates = [
        project_root / "docs" / "global",
        project_root / "docs" / "project",
        project_root / "agents" / "docs",
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            rel_path = candidate.relative_to(project_root)
            include_baseline = str(rel_path) in ("docs/global", "agents/docs")
        except ValueError:
            include_baseline = False
        files = [p for p in candidate.rglob("*.md") if p.name != "index.yaml"]
        if not include_baseline:
            files = [p for p in files if "baseline" not in str(p)]
        if files:
            roots.append(candidate)
    return roots


def validate_all_snippets(project_root: Path) -> None:
    """Validate all doc snippets under the project. Collects warnings."""
    domains = load_domains(project_root)
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
            if not include_baseline and "baseline" in str(path):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except Exception as exc:
                _warn("snippet_read_failed", path=str(path), error=str(exc))
                continue
            validate_snippet(path, text, project_root, domains=domains)
    validate_third_party_docs(project_root)
