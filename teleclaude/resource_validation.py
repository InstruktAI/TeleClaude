"""Unified validation for doc snippets and agent artifacts.

This module is the single source of truth for validating all markdown resources:
- Doc snippets (frontmatter, structure, sections, inline refs)
- Agent artifacts (commands, agents, skills — schema, frontmatter, refs)
- Baseline index refs
- Third-party doc sources

Called by ``telec sync`` and pre-commit hooks. Read-only — never modifies files.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Mapping

import frontmatter
import yaml
from typing_extensions import TypedDict

from teleclaude.types.todos import TodoState

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from teleclaude.constants import TAXONOMY_TYPES, TYPE_SUFFIX  # noqa: E402
from teleclaude.snippet_validation import (  # noqa: E402
    expected_snippet_id_for_path,
    load_domains,
    validate_inline_ref_format,
    validate_snippet_id_format,
)

# ---------------------------------------------------------------------------
# Shared patterns
# ---------------------------------------------------------------------------

_REQUIRED_READS_HEADER = re.compile(r"^##\s+Required reads\s*$", re.IGNORECASE)
_SOURCES_HEADER = re.compile(r"^##\s+Sources\s*$", re.IGNORECASE)
_SEE_ALSO_HEADER = re.compile(r"^##\s+See also\s*$", re.IGNORECASE)
_HEADER_LINE = re.compile(r"^#{1,6}\s+")
_REQUIRED_READ_LINE = re.compile(r"^\s*-\s*@(\S+)\s*$")
_H1_LINE = re.compile(r"^#\s+")
_H2_LINE = re.compile(r"^##\s+")
_INLINE_REF_LINE = re.compile(r"^\s*(?:-\s*)?@\S+")
_CODE_FENCE_LINE = re.compile(r"^```")
_INLINE_CODE_SPAN = re.compile(r"`[^`]*`")
_SEE_ALSO_LIST_LINE = re.compile(r"^\s*-\s+(.+)$")

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "scripts" / "snippet_schema.yaml"

_ARTIFACT_REF_ORDER = TAXONOMY_TYPES.copy()

# ---------------------------------------------------------------------------
# Warning collection
# ---------------------------------------------------------------------------


class ValidationWarning(TypedDict):
    code: str
    path: str


_WARNINGS: list[dict[str, str]] = []


def _warn(code: str, path: str = "", **kwargs: str) -> None:
    payload: dict[str, str] = {"code": code, "path": path}
    payload.update({k: str(v) for k, v in kwargs.items()})
    _WARNINGS.append(payload)


def get_warnings() -> list[dict[str, str]]:
    return list(_WARNINGS)


def clear_warnings() -> None:
    _WARNINGS.clear()


# ---------------------------------------------------------------------------
# Schema loading
# ---------------------------------------------------------------------------


class GlobalSchemaConfig(TypedDict, total=False):
    required_reads_title: str
    see_also_title: str
    sources_title: str
    require_h1: bool
    require_h1_first: bool
    require_required_reads: bool
    required_reads_header_level: int
    see_also_header_level: int
    sources_header_level: int
    allow_h3: bool


class SectionSchema(TypedDict):
    required: list[str]
    allowed: list[str]


class SchemaConfig(TypedDict):
    global_: GlobalSchemaConfig
    sections: dict[str, SectionSchema]


def _as_str_list(value: object) -> list[str]:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return []


def _load_schema() -> SchemaConfig:
    if not _SCHEMA_PATH.exists():
        return {"global_": {}, "sections": {}}
    raw = yaml.safe_load(_SCHEMA_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return {"global_": {}, "sections": {}}

    global_raw = raw.get("global", {})
    global_cfg: GlobalSchemaConfig = {}
    if isinstance(global_raw, dict):
        for key, value in global_raw.items():
            if key in {
                "required_reads_title",
                "see_also_title",
                "sources_title",
            } and isinstance(value, str):
                global_cfg[key] = value
            elif key in {
                "require_h1",
                "require_h1_first",
                "require_required_reads",
                "allow_h3",
            } and isinstance(value, bool):
                global_cfg[key] = value
            elif key in {
                "required_reads_header_level",
                "see_also_header_level",
                "sources_header_level",
            } and isinstance(value, int):
                global_cfg[key] = value

    sections_raw = raw.get("sections", {})
    sections: dict[str, SectionSchema] = {}
    if isinstance(sections_raw, dict):
        for section_name, section_raw in sections_raw.items():
            if not isinstance(section_raw, dict):
                continue
            required = _as_str_list(section_raw.get("required"))
            allowed = _as_str_list(section_raw.get("allowed"))
            sections[str(section_name)] = {"required": required, "allowed": allowed}

    return {"global_": global_cfg, "sections": sections}


_SCHEMA = _load_schema()


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

    raw_role = meta.get("role")
    if raw_role is not None:
        from teleclaude.constants import ROLE_VALUES

        if not isinstance(raw_role, str) or raw_role not in ROLE_VALUES:
            _warn("snippet_invalid_role_value", path=str(path), value=str(raw_role))

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
    for line in lines:
        if not line.startswith("@"):
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
    """Resolve a See Also soft reference to an absolute path for existence check.

    See Also refs are NOT ``@`` refs.  They use one of two prefixes:

    * ``docs/...`` — project-relative, resolved against *project_root*.
    * ``~/.teleclaude/docs/...`` — global, mapped back to source at
      ``docs/global/`` in the repo for validation (the deploy target may be
      stale or empty).
    """
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
            _warn(
                "snippet_see_also_bad_prefix",
                path=str(path),
                ref=raw,
                expected="~/.teleclaude/docs/...",
            )
            return
    else:
        if not raw.startswith("docs/") and not raw.startswith("~/.teleclaude/docs/"):
            _warn(
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
    for line in lines:
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

    role_val = meta.get("role")
    if role_val is not None:
        from teleclaude.constants import ROLE_VALUES

        if not isinstance(role_val, str) or role_val not in ROLE_VALUES:
            _warn("snippet_invalid_role_value", path=str(path), value=str(role_val))

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


_MARKDOWN_LINK_RE = re.compile(r"^\[([^\]]+)\]\((https?://[^)]+)\)$")


def _extract_markdown_link_url(value: str) -> str | None:
    """Extract URL from a markdown link like [text](https://...)."""
    m = _MARKDOWN_LINK_RE.match(value)
    return m.group(2) if m else None


def _check_url_alive(url: str, *, timeout: int = 8) -> bool:
    headers = {"User-Agent": "TeleClaude/1.0"}
    try:
        req = urllib.request.Request(url, method="HEAD", headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 400
    except urllib.error.HTTPError as exc:
        # Some docs block HEAD; retry with GET before declaring unreachable.
        if exc.code >= 400:
            try:
                req = urllib.request.Request(url, method="GET", headers=headers)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.status < 400
            except Exception:
                return False
        return False
    except Exception:
        return False


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
                if not _check_url_alive(url):
                    _warn("third_party_source_unreachable", path=str(path), source=url)
                continue
            _warn("third_party_source_invalid", path=str(path), source=source)


# ---------------------------------------------------------------------------
# Agent artifact validation
# ---------------------------------------------------------------------------


def _taxonomy_from_ref(ref: str) -> str | None:
    for taxonomy in _ARTIFACT_REF_ORDER:
        if f"/{taxonomy}/" in ref:
            return taxonomy
    return None


def _extract_artifact_required_reads(lines: list[str]) -> list[str]:
    """Extract ``@`` refs from a Required reads section after the H1 title."""
    refs: list[str] = []
    in_required_reads = False
    for raw in lines:
        stripped = raw.strip()
        if stripped.lower() == "## required reads":
            in_required_reads = True
            continue
        if in_required_reads:
            if stripped.startswith("## ") or stripped.startswith("# "):
                break
            if stripped.startswith("@"):
                refs.append(stripped[1:].strip())
                continue
            if stripped.startswith("- @"):
                refs.append(stripped[3:].strip())
                continue
            if not stripped:
                continue
            break
    return refs


def _next_nonblank(lines: list[str], idx: int) -> tuple[str | None, int]:
    while idx < len(lines) and not lines[idx].strip():
        idx += 1
    if idx >= len(lines):
        return None, idx
    return lines[idx], idx


def validate_artifact_frontmatter(post: frontmatter.Post, path: str, *, kind: str) -> None:
    """Validate frontmatter fields for an agent artifact."""
    description = post.metadata.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError(f"{kind.title()} {path} is missing frontmatter 'description'")
    if kind == "skill":
        name = post.metadata.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"Skill {path} is missing frontmatter 'name'")


def validate_artifact_body(post: frontmatter.Post, path: str, *, kind: str) -> None:
    """Validate body structure of an agent artifact (command, agent, or skill)."""
    argument_hint = post.metadata.get("argument-hint")
    if kind == "command" and argument_hint is not None and not isinstance(argument_hint, str):
        raise ValueError(f"{path} has invalid frontmatter 'argument-hint' (must be a string)")
    lines = post.content.splitlines()
    first_line, h1_idx = _next_nonblank(lines, 0)
    if first_line is None or not first_line.startswith("# "):
        raise ValueError(f"{path} must start with an H1 title")

    required_reads_idx = None
    required_reads_end = None
    for i in range(h1_idx + 1, len(lines)):
        if lines[i].strip().lower() == "## required reads":
            required_reads_idx = i
            j = i + 1
            while j < len(lines):
                stripped = lines[j].strip()
                if not stripped:
                    j += 1
                    continue
                if stripped.startswith("@") or stripped.startswith("- @"):
                    j += 1
                    continue
                if stripped.startswith("# "):
                    break
                if stripped.startswith("## ") and stripped.lower() != "## required reads":
                    break
                break
            required_reads_end = j
            break

    if required_reads_idx is not None:
        for i in range(h1_idx + 1, required_reads_idx):
            stripped = lines[i].strip()
            if stripped.startswith("## "):
                raise ValueError(f"{path} must place Required reads before other H2 sections")
        for i in range(required_reads_idx + 1, required_reads_end or len(lines)):
            stripped = lines[i].strip()
            if not stripped:
                continue
            if stripped.startswith("@") or stripped.startswith("- @"):
                continue
            break

    refs = _extract_artifact_required_reads(lines)
    _validate_required_reads_order(refs, path)

    first_section_idx = None
    for i in range(h1_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("## ") and stripped.lower() != "## required reads":
            first_section_idx = i
            break

    if first_section_idx is None:
        raise ValueError(f"{path} is missing required section headings")

    if kind in {"command", "agent"}:
        has_role = any(line.strip().startswith("You are now the ") for line in lines[h1_idx + 1 : first_section_idx])
        if not has_role:
            raise ValueError(f"{path} must include a role activation line before the first section")
    else:
        if any(line.strip().startswith("You are now the ") for line in lines):
            raise ValueError(f"{path} must not include a role activation line")

    allowed_map = {
        "command": ["Purpose", "Inputs", "Outputs", "Steps", "Examples"],
        "skill": ["Purpose", "Scope", "Inputs", "Outputs", "Procedure", "Examples"],
        "agent": ["Purpose", "Scope", "Inputs", "Outputs", "Procedure", "Examples"],
    }
    required_map = {
        "command": ["Purpose", "Inputs", "Outputs", "Steps"],
        "skill": ["Purpose", "Scope", "Inputs", "Outputs", "Procedure"],
        "agent": ["Purpose", "Scope", "Inputs", "Outputs", "Procedure"],
    }
    allowed = allowed_map[kind]
    required = required_map[kind]

    headings: list[str] = []
    in_required_reads = False
    for idx, raw in enumerate(lines):
        stripped = raw.strip()
        if stripped.lower() == "## required reads":
            in_required_reads = True
            continue
        if in_required_reads:
            if stripped.startswith("## ") or stripped.startswith("# "):
                in_required_reads = False
            else:
                continue
        if stripped.startswith("@") or stripped.startswith("- @"):
            raise ValueError(f"{path} has inline refs outside the required reads block")
        if stripped.startswith("# "):
            if idx != h1_idx:
                raise ValueError(f"{path} must only have one H1 title")
        if stripped.startswith("### "):
            raise ValueError(f"{path} must use H2 headings only for schema sections")
        if stripped.startswith("## "):
            title = stripped[3:].strip()
            if title.lower() == "required reads":
                continue
            headings.append(title)

    if not headings:
        raise ValueError(f"{path} is missing required section headings")

    for heading in headings:
        if heading not in allowed:
            raise ValueError(f"{path} has invalid section heading '{heading}'")

    if headings != required and headings != required + ["Examples"]:
        raise ValueError(f"{path} section order must be: {' → '.join(required)} (optional Examples at end)")


def _validate_required_reads_order(refs: list[str], path: str) -> None:
    last_index = -1
    for ref in refs:
        taxonomy = _taxonomy_from_ref(ref)
        if not taxonomy:
            continue
        index = _ARTIFACT_REF_ORDER.index(taxonomy)
        if index < last_index:
            raise ValueError(f"{path} required reads are out of order; expected {' → '.join(_ARTIFACT_REF_ORDER)}")
        last_index = index


def validate_artifact_refs_exist(refs: list[str], path: str, *, project_root: Path) -> None:
    """Raise if any artifact ``@`` ref points to a non-existent file."""
    current_path = Path(path)
    for ref in refs:
        resolved = resolve_ref_path(ref, root_path=project_root, current_path=current_path)
        if not resolved or not resolved.exists():
            raise ValueError(f"{path} references non-existent file: {ref}")


def validate_artifact(post: frontmatter.Post, path: str, *, kind: str, project_root: Path) -> None:
    """Full validation of an agent artifact."""
    validate_artifact_frontmatter(post, path, kind=kind)
    validate_artifact_body(post, path, kind=kind)
    refs = _extract_artifact_required_reads(post.content.splitlines())
    if refs:
        validate_artifact_refs_exist(refs, path, project_root=project_root)
    if kind == "skill":
        name = post.metadata.get("name")
        dirname = Path(path).parent.name
        if isinstance(name, str) and name != dirname:
            raise ValueError(f"Skill name '{name}' must match folder '{dirname}'")


# ---------------------------------------------------------------------------
# Top-level validation entry points
# ---------------------------------------------------------------------------


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


def validate_all_artifacts(project_root: Path) -> list[str]:
    """Validate all agent artifact source files. Returns list of errors."""
    teleclaude_root = REPO_ROOT
    is_mother_project = Path(project_root).resolve() == teleclaude_root.resolve()
    agents_root = teleclaude_root / "agents"
    dot_agents_root = project_root / ".agents"

    global_sources: list[dict[str, str]] = []
    if is_mother_project:
        global_sources = [
            {
                "label": "agents",
                "agents_dir": str(agents_root / "agents"),
                "commands": str(agents_root / "commands"),
                "skills": str(agents_root / "skills"),
            }
        ]
    local_sources = [
        {
            "label": ".agents",
            "agents_dir": str(dot_agents_root / "agents"),
            "commands": str(dot_agents_root / "commands"),
            "skills": str(dot_agents_root / "skills"),
        },
    ]

    kind_map = {"agents_dir": "agent", "commands": "command", "skills": "skill"}
    errors: list[str] = []

    for sources in (global_sources, local_sources):
        for source in sources:
            for dir_key, kind in kind_map.items():
                source_dir = source.get(dir_key)
                if not source_dir or not os.path.isdir(source_dir):
                    continue
                if kind == "skill":
                    items = [f for f in os.listdir(source_dir) if os.path.isdir(os.path.join(source_dir, f))]
                else:
                    items = [f for f in os.listdir(source_dir) if f.endswith(".md")]
                for item in sorted(items):
                    if kind == "skill":
                        item_path = os.path.join(source_dir, item, "SKILL.md")
                    else:
                        item_path = os.path.join(source_dir, item)
                    if not os.path.exists(item_path):
                        continue
                    try:
                        with open(item_path, "r") as f:
                            post = frontmatter.load(f)
                        validate_artifact(post, item_path, kind=kind, project_root=project_root)
                    except Exception as e:
                        errors.append(str(e))
    return errors


def _job_slug_to_spec_filename(job_slug: str) -> str:
    return f"{job_slug.replace('_', '-')}.md"


def validate_jobs_config(project_root: Path) -> list[str]:
    """Validate project job config in teleclaude.yml.

    Checks schedule shape, execution mode contract, and job/spec/module references.
    """
    config_path = project_root / "teleclaude.yml"
    if not config_path.exists():
        return []

    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return [f"{config_path}: invalid YAML ({exc})"]

    if not isinstance(config, dict):
        return [f"{config_path}: expected top-level mapping"]

    jobs = config.get("jobs", {})
    if not isinstance(jobs, dict):
        return [f"{config_path}: jobs must be a mapping"]

    allowed_schedules = {"hourly", "daily", "weekly", "monthly"}
    errors: list[str] = []

    for name, raw in jobs.items():
        if not isinstance(raw, dict):
            errors.append(f"{config_path}: jobs.{name} must be a mapping")
            continue
        job_cfg = raw

        schedule = job_cfg.get("schedule")
        if not isinstance(schedule, str) or schedule not in allowed_schedules:
            errors.append(f"{config_path}: jobs.{name}.schedule must be one of {sorted(allowed_schedules)}")

        preferred_hour = job_cfg.get("preferred_hour", 6)
        if not isinstance(preferred_hour, int) or not (0 <= preferred_hour <= 23):
            errors.append(f"{config_path}: jobs.{name}.preferred_hour must be int 0..23")

        preferred_weekday = job_cfg.get("preferred_weekday", 0)
        if not isinstance(preferred_weekday, int) or not (0 <= preferred_weekday <= 6):
            errors.append(f"{config_path}: jobs.{name}.preferred_weekday must be int 0..6")

        preferred_day = job_cfg.get("preferred_day", 1)
        if not isinstance(preferred_day, int) or not (1 <= preferred_day <= 31):
            errors.append(f"{config_path}: jobs.{name}.preferred_day must be int 1..31")

        is_agent = str(job_cfg.get("type", "")) == "agent"
        if is_agent:
            if "message" in job_cfg:
                errors.append(f"{config_path}: jobs.{name}.message is not allowed for agent jobs")
            job_ref = job_cfg.get("job")
            if not isinstance(job_ref, str) or not job_ref.strip():
                errors.append(f"{config_path}: jobs.{name}.job is required for agent jobs")
            else:
                spec_file = project_root / "docs" / "project" / "spec" / "jobs" / _job_slug_to_spec_filename(job_ref)
                if not spec_file.exists():
                    errors.append(f"{config_path}: jobs.{name}.job references missing spec {spec_file}")
        else:
            script_ref = job_cfg.get("script")
            if not isinstance(script_ref, str) or not script_ref.strip():
                # Default python-job contract: module should exist at jobs/{name}.py
                python_module_path = project_root / "jobs" / f"{name}.py"
                if not python_module_path.exists():
                    errors.append(
                        f"{config_path}: jobs.{name} has no script and missing python module {python_module_path}"
                    )

    return errors


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


def validate_todo(slug: str, project_root: Path) -> list[str]:
    """Validate a todo directory structure and state.json schema."""
    todos_root = project_root / "todos"
    todo_dir = todos_root / slug
    if not todo_dir.is_dir():
        return [f"Todo directory missing: {todo_dir}"]

    errors = []

    # 1. state.json schema validation
    state_path = todo_dir / "state.json"
    if not state_path.exists():
        errors.append(f"{slug}: missing state.json")
    else:
        try:
            content = state_path.read_text(encoding="utf-8")
            data = json.loads(content)
            TodoState.model_validate(data)
        except Exception as exc:
            errors.append(f"{slug}: state.json schema violation: {exc}")

    # 2. Required files for Ready state
    # If phase is pending and score >= 8, requirements and implementation plan MUST exist
    if state_path.exists():
        try:
            state = TodoState.model_validate(json.loads(state_path.read_text(encoding="utf-8")))
            if state.phase == "pending" and state.dor and state.dor.score >= 8:
                if not (todo_dir / "requirements.md").exists():
                    errors.append(f"{slug}: marked as Ready (score {state.dor.score}) but missing requirements.md")
                if not (todo_dir / "implementation-plan.md").exists():
                    errors.append(
                        f"{slug}: marked as Ready (score {state.dor.score}) but missing implementation-plan.md"
                    )
        except Exception:
            pass  # already reported in schema check

    return errors


def validate_all_todos(project_root: Path) -> list[str]:
    """Enumerate and validate all active todos."""
    todos_root = project_root / "todos"
    if not todos_root.is_dir():
        return []

    # Exclude delivered and icebox
    delivered = set()
    delivered_path = todos_root / "delivered.md"
    if delivered_path.exists():
        # simple regex to extract slugs from markdown table
        delivered = set(re.findall(r"\|\s*([a-z0-9-]+)\s*\|", delivered_path.read_text(encoding="utf-8")))

    icebox = set()
    icebox_path = todos_root / "icebox.md"
    if icebox_path.exists():
        icebox = set(re.findall(r"\|\s*([a-z0-9-]+)\s*\|", icebox_path.read_text(encoding="utf-8")))

    errors = []
    if not todos_root.exists():
        return []

    for entry in todos_root.iterdir():
        if entry.is_dir() and entry.name not in delivered and entry.name not in icebox:
            # Skip hidden dirs or __pycache__
            if entry.name.startswith(".") or entry.name == "__pycache__":
                continue
            errors.extend(validate_todo(entry.name, project_root))

    return errors
