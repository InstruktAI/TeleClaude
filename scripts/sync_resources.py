#!/usr/bin/env -S uv run --quiet
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from typing import Mapping, NotRequired, TypedDict

import frontmatter
import yaml
from instrukt_ai_logging import get_logger

# Allow running from any working directory by anchoring imports at repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from teleclaude.constants import TYPE_SUFFIX as _TYPE_SUFFIX
from teleclaude.snippet_validation import (
    expected_snippet_id_for_path,
    load_domains,
    validate_inline_ref_format,
    validate_snippet_id_format,
)

logger = get_logger(__name__)
_WARNINGS: list[dict[str, str]] = []
_LOG_WARNINGS = True

_REQUIRED_READS_HEADER = re.compile(r"^##\s+Required reads\s*$", re.IGNORECASE)
_SOURCES_HEADER = re.compile(r"^##\s+Sources\s*$", re.IGNORECASE)
_SEE_ALSO_HEADER = re.compile(r"^##\s+See also\s*$", re.IGNORECASE)
_HEADER_LINE = re.compile(r"^#{1,6}\s+")
_REQUIRED_READ_LINE = re.compile(r"^\s*-\s*@(\S+)\s*$")
_H1_LINE = re.compile(r"^#\s+")
_H2_LINE = re.compile(r"^##\s+")
_INLINE_REF_LINE = re.compile(r"^\s*(?:-\s*)?@\S+")
_CODE_FENCE_LINE = re.compile(r"^```")

_SCHEMA_PATH = Path(__file__).resolve().parent / "snippet_schema.yaml"


def _teleclaude_root() -> str:
    """Return teleclaude root path with tilde (portable)."""
    return "~/.teleclaude"


def _get_allowed_ref_prefixes() -> tuple[str, str]:
    """Return allowed reference prefixes (absolute home + repo-relative)."""
    abs_root = str(Path.home() / ".teleclaude")
    return (f"@{abs_root}/docs/", "@docs/")


def _is_third_party_snippet(path: Path) -> bool:
    return "third-party" in path.parts


def _extract_sources_section(lines: list[str]) -> list[str]:
    sources: list[str] = []
    in_sources = False
    for line in lines:
        if _SOURCES_HEADER.match(line):
            in_sources = True
            continue
        if in_sources and _H2_LINE.match(line):
            break
        if in_sources:
            stripped = line.strip()
            if stripped.startswith("- "):
                sources.append(stripped[2:].strip())
    return [s for s in sources if s]


def _is_context7_id(value: str) -> bool:
    return value.startswith("/api/library/") or value.startswith("/org/")


def _is_web_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _check_url_alive(url: str, *, timeout: int = 8) -> bool:
    try:
        result = subprocess.run(
            [
                "curl",
                "-sS",
                "-I",
                "-L",
                "--max-time",
                str(timeout),
                url,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception:
        return False
    return result.returncode == 0


def _iter_inline_refs(lines: list[str]) -> list[str]:
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


def _resolve_inline_ref(project_root: Path, snippet_path: Path, ref: str) -> Path | None:
    if not ref.startswith("@"):
        return None
    target = ref[1:]
    if target.startswith("~"):
        return Path(target).expanduser()
    if target.startswith("/"):
        return Path(target)
    if target.startswith("./") or target.startswith("../"):
        return (snippet_path.parent / target).resolve()
    return (project_root / target).resolve()


def _collect_inline_ref_errors(
    project_root: Path, snippet_path: Path, lines: list[str], *, domains: set[str]
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    allowed_prefixes = _get_allowed_ref_prefixes()
    for ref in _iter_inline_refs(lines):
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
        resolved = _resolve_inline_ref(project_root, snippet_path, ref)
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


def _validate_third_party_docs(project_root: Path) -> None:
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
            if _is_web_url(source):
                if not _check_url_alive(source):
                    _warn("third_party_source_unreachable", path=str(path), source=source)
                continue
            _warn("third_party_source_invalid", path=str(path), source=source)


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


def _resolve_requires(
    file_path: Path,
    requires: list[str],
    snippets_root: Path,
    project_root: Path,
    snippet_path_to_id: dict[str, str],
) -> list[str]:
    resolved: list[str] = []
    home_prefix = str(Path.home())
    for req in requires:
        if not isinstance(req, str):
            continue
        if not req.endswith(".md"):
            if req.startswith(home_prefix):
                resolved.append(req.replace(home_prefix, "~", 1))
            else:
                resolved.append(req)
            continue
        candidate = Path(req).expanduser()
        if not candidate.is_absolute():
            absolute = (file_path.parent / candidate).resolve()
        else:
            absolute = candidate.resolve()
        try:
            rel_to_snippets = absolute.relative_to(snippets_root)
        except ValueError:
            try:
                resolved.append(str(absolute.relative_to(project_root)))
            except ValueError:
                abs_str = str(absolute)
                if abs_str.startswith(home_prefix):
                    abs_str = abs_str.replace(home_prefix, "~", 1)
                resolved.append(abs_str)
            continue
        snippet_id = snippet_path_to_id.get(rel_to_snippets.as_posix())
        resolved.append(snippet_id if snippet_id else str(rel_to_snippets))
    return resolved


def _extract_required_reads(content: str) -> list[str]:
    lines = content.splitlines()
    header_idx = None
    for idx, line in enumerate(lines):
        if _REQUIRED_READS_HEADER.match(line):
            header_idx = idx
            break
    if header_idx is None:
        return []
    section_start = header_idx + 1
    section_end = next(
        (i for i in range(section_start, len(lines)) if _HEADER_LINE.match(lines[i])),
        len(lines),
    )
    refs: list[str] = []
    for line in lines[section_start:section_end]:
        match = _REQUIRED_READ_LINE.match(line)
        if match:
            refs.append(match.group(1))
    return refs


def _warn(code: str, path: str = "", **kwargs: str) -> None:
    payload = {"code": code, "path": path}
    payload.update({k: str(v) for k, v in kwargs.items()})
    _WARNINGS.append(payload)
    if _LOG_WARNINGS:
        logger.warning(code, **payload)


def _normalize_section_title(title: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", " ", title).strip().lower()
    return re.sub(r"\s+", " ", cleaned)


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


def _infer_type_from_path(file_path: Path) -> str | None:
    parts = [p for p in file_path.parts]
    try:
        baseline_idx = parts.index("baseline")
    except ValueError:
        return None
    if baseline_idx + 1 >= len(parts):
        return None
    folder = parts[baseline_idx + 1]
    return folder if folder in _TYPE_SUFFIX else None


def _normalize_title(
    file_path: Path,
    content: str,
    declared_type: str | None,
) -> str:
    suffix = _TYPE_SUFFIX.get((declared_type or "").lower())
    if not suffix:
        inferred = _infer_type_from_path(file_path)
        suffix = _TYPE_SUFFIX.get(inferred) if inferred else None
    if not suffix:
        return content
    lines = content.splitlines()
    if not lines:
        return content
    if not _H1_LINE.match(lines[0]):
        return content
    title = lines[0].lstrip("#").strip()
    expected = f" — {suffix}"
    if title.endswith(expected):
        return content
    if " — " in title:
        base = title.split(" — ")[0].strip()
    else:
        base = title
    lines[0] = f"# {base}{expected}"
    return "\n".join(lines) + ("\n" if content.endswith("\n") else "")


def _normalize_titles(snippets_root: Path, project_root: Path, *, domains: set[str]) -> None:
    for path in sorted(snippets_root.rglob("*.md")):
        if path.name == "index.yaml":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            _warn("title_read_failed", path=str(path), error=str(exc))
            continue
        declared_type = None
        if text.lstrip().startswith("---"):
            try:
                post = frontmatter.loads(text)
                meta = post.metadata or {}
                declared_type = meta.get("type") if isinstance(meta.get("type"), str) else None
                body = post.content
            except Exception:
                body = text
        else:
            body = text
        updated = _normalize_title(path, body, declared_type)
        full_content = text
        if updated != body:
            if text.lstrip().startswith("---"):
                try:
                    post = frontmatter.loads(text)
                    post.content = updated
                    full_content = frontmatter.dumps(post)
                    path.write_text(full_content, encoding="utf-8")
                except Exception as exc:
                    _warn("title_write_failed", path=str(path), error=str(exc))
                    full_content = text
            else:
                try:
                    full_content = updated
                    path.write_text(full_content, encoding="utf-8")
                except Exception as exc:
                    _warn("title_write_failed", path=str(path), error=str(exc))
                    full_content = text
        _validate_snippet_format(path, full_content, project_root, domains=domains)


def _validate_snippet_format(path: Path, content: str, project_root: Path, *, domains: set[str]) -> None:
    if path.name == "index.md" and "baseline" in path.parts:
        lines = [line for line in content.splitlines() if line.strip()]
        for line in lines:
            if not line.startswith("@"):
                _warn("snippet_baseline_index_invalid_line", path=str(path), line=line)
        return
    has_frontmatter = content.lstrip().startswith("---")
    if has_frontmatter:
        try:
            post = frontmatter.loads(content)
            meta = post.metadata or {}
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
            if "@" in line:
                if in_see_also:
                    _warn("snippet_see_also_inline_ref", path=str(path), line=line.strip())
                elif not in_required_reads:
                    _warn("snippet_required_reads_outside_section", path=str(path), line=line.strip())

    h2_titles: list[str] = []
    for line in lines:
        if _H2_LINE.match(line):
            h2_titles.append(line.lstrip("#").strip())
    normalized_titles = [_normalize_section_title(t) for t in h2_titles]

    if "see also" in normalized_titles:
        last_h2 = normalized_titles[-1] if normalized_titles else ""
        if last_h2 != "see also":
            _warn("snippet_see_also_not_last", path=str(path))
    if sources_found and sources_header_idx is not None:
        if not lines[sources_header_idx].startswith("## "):
            _warn("snippet_sources_header_level", path=str(path))

    for error in _collect_inline_ref_errors(project_root, path, lines, domains=domains):
        _warn(error["code"], **{k: v for k, v in error.items() if k != "code"})

    snippet_type = None
    if isinstance(meta.get("type"), str):
        snippet_type = meta.get("type")
    if "baseline" not in path.parts:
        if not has_frontmatter:
            _warn("snippet_missing_frontmatter", path=str(path))
        else:
            for field in ("id", "type", "scope", "description"):
                if not isinstance(meta.get(field), str) or not meta.get(field):
                    _warn("snippet_missing_frontmatter_field", path=str(path), field=field)
    if _is_third_party_snippet(path):
        sources = _extract_sources_section(lines)
        if not sources:
            _warn("snippet_missing_sources", path=str(path))
        for source in sources:
            if _is_context7_id(source):
                continue
            if _is_web_url(source):
                if not _check_url_alive(source):
                    _warn("snippet_source_unreachable", path=str(path), source=source)
                continue
            _warn("snippet_source_invalid", path=str(path), source=source)
    if not snippet_type:
        snippet_type = _infer_type_from_path(path)
    if snippet_type:
        type_key = snippet_type.lower()
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


class SnippetEntry(TypedDict):
    id: str
    description: str
    type: str
    scope: str
    path: str
    requires: NotRequired[list[str]]
    source_project: NotRequired[str]  # Added for tracking ownership in global docs


class IndexPayload(TypedDict):
    project_root: str
    snippets_root: str
    snippets: list[SnippetEntry]


def _snippet_files(snippets_root: Path) -> list[Path]:
    return [path for path in snippets_root.rglob("*.md") if path.name != "index.yaml" and "baseline" not in str(path)]


def _ensure_project_config(project_root: Path) -> None:
    config_path = project_root / "teleclaude.yml"
    if config_path.exists():
        return
    config_path.write_text(
        "business:\n  domains:\n    software-development: docs\n",
        encoding="utf-8",
    )


def _iter_snippet_roots(project_root: Path) -> list[Path]:
    roots: list[Path] = []
    # New structure: docs/global and docs/project
    # Old structure (for backward compatibility): agents/docs
    candidates = [
        project_root / "docs" / "global",
        project_root / "docs" / "project",
        project_root / "agents" / "docs",  # Deprecated, for backward compatibility
    ]
    for candidate in candidates:
        if candidate.exists() and _snippet_files(candidate):
            roots.append(candidate)
    return roots


def _strip_baseline_frontmatter(project_root: Path) -> list[str]:
    baseline_root = project_root / "agents" / "docs" / "baseline"
    if not baseline_root.exists():
        return []
    violations: list[str] = []
    for path in sorted(baseline_root.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning("baseline_read_failed", path=str(path), error=str(exc))
            continue
        if text.lstrip().startswith("---"):
            try:
                rel = path.relative_to(project_root)
            except ValueError:
                rel = path
            violations.append(str(rel))
            lines = text.splitlines(keepends=True)
            end_idx = None
            for idx in range(1, len(lines)):
                if lines[idx].strip() == "---":
                    end_idx = idx
                    break
            if end_idx is None:
                continue
            stripped = "".join(lines[end_idx + 1 :]).lstrip()
            try:
                path.write_text(stripped, encoding="utf-8")
            except Exception as exc:
                logger.warning("baseline_strip_failed", path=str(path), error=str(exc))
    return violations


def _write_baseline_index(project_root: Path) -> None:
    baseline_root = project_root / "agents" / "docs" / "baseline"
    if not baseline_root.exists():
        return
    root = _teleclaude_root()
    entries: list[str] = []
    for path in sorted(baseline_root.rglob("*.md")):
        if path.name == "index.md":
            continue
        rel = path.relative_to(baseline_root).as_posix()
        entries.append(f"@{root}/docs/baseline/{rel}")
    if not entries:
        return
    baseline_index = baseline_root / "index.md"
    content = "\n".join(
        [
            *entries,
            "",
        ]
    )
    baseline_index.write_text(content, encoding="utf-8")


def _write_third_party_index(project_root: Path) -> None:
    third_party_root = project_root / "docs" / "third-party"
    if not third_party_root.exists():
        return
    entries: list[str] = []
    docs_root = project_root / "docs"
    for path in sorted(third_party_root.rglob("*.md")):
        if path.name == "index.md":
            continue
        try:
            rel = path.relative_to(docs_root).as_posix()
        except ValueError:
            continue
        entries.append(f"@docs/{rel}")
    if not entries:
        return
    index_path = third_party_root / "index.md"
    content = "\n".join([*entries, ""])
    if index_path.exists():
        existing = index_path.read_text(encoding="utf-8")
        if existing == content:
            return
    index_path.write_text(content, encoding="utf-8")


def _remove_non_baseline_indexes(snippets_root: Path) -> list[str]:
    removed: list[str] = []
    for path in sorted(snippets_root.rglob("index.md")):
        if "baseline" in path.parts:
            continue
        try:
            path.unlink()
            removed.append(str(path))
            logger.warning("index_removed", path=str(path))
            print(f"Removed unnecessary index.md: {path}. Avoid creating index.md files outside baseline.")
        except Exception as exc:
            logger.warning("index_remove_failed", path=str(path), error=str(exc))
    return removed


def build_index_payload(project_root: Path, snippets_root: Path) -> IndexPayload:
    violations = _strip_baseline_frontmatter(project_root)
    if violations:
        logger.warning("baseline_frontmatter_removed", paths=violations)
        print("Unexpected baseline frontmatter was found and cleaned.")
    _write_baseline_index(project_root)
    _remove_non_baseline_indexes(snippets_root)
    domains = load_domains(project_root)
    _normalize_titles(snippets_root, project_root, domains=domains)
    if not snippets_root.exists():
        return {
            "project_root": str(project_root),
            "snippets_root": str(snippets_root),
            "snippets": [],
        }

    snippet_path_to_id: dict[str, str] = {}
    snippet_cache: list[tuple[Path, Mapping[str, object], str]] = []
    snippet_files = sorted(_snippet_files(snippets_root))
    if not snippet_files:
        return {
            "project_root": str(project_root),
            "snippets_root": str(snippets_root),
            "snippets": [],
        }
    for file_path in snippet_files:
        post = frontmatter.load(file_path)
        metadata: Mapping[str, object] = post.metadata or {}
        snippet_id = metadata.get("id")
        if isinstance(snippet_id, str):
            snippet_path_to_id[str(file_path.relative_to(snippets_root))] = snippet_id
        snippet_cache.append((file_path, metadata, post.content))

    snippets: list[SnippetEntry] = []
    for file_path, metadata, content in snippet_cache:
        snippet_id = metadata.get("id")
        description = metadata.get("description")
        snippet_type = metadata.get("type")
        snippet_scope = metadata.get("scope")
        if (
            not isinstance(snippet_id, str)
            or not isinstance(description, str)
            or not isinstance(snippet_type, str)
            or not isinstance(snippet_scope, str)
        ):
            continue
        requires_list = _extract_required_reads(content)
        resolved_refs = _resolve_requires(file_path, requires_list, snippets_root, project_root, snippet_path_to_id)
        try:
            relative_path = str(file_path.relative_to(project_root))
        except ValueError:
            relative_path = str(file_path)
        entry: SnippetEntry = {
            "id": snippet_id,
            "description": description,
            "type": snippet_type,
            "scope": snippet_scope,
            "path": relative_path,
        }
        if resolved_refs:
            entry["requires"] = resolved_refs
        snippets.append(entry)

    snippets.sort(key=lambda entry: entry["id"])

    # Check for global ID collisions before building payload
    _check_global_collisions(snippets, project_root, snippets_root)

    # Add source_project to snippets for global tracking
    project_name = _get_project_name(project_root)
    for snippet in snippets:
        snippet["source_project"] = project_name

    # Use tilde for portable paths
    # For docs/global (or agents/docs), use ~/.teleclaude
    # For other docs, use the actual project root with tilde
    try:
        rel_path = snippets_root.relative_to(project_root)
        is_global = str(rel_path) in ("docs/global", "agents/docs")
    except ValueError:
        is_global = False

    if is_global:
        root = _teleclaude_root()
        snippets_root_str = f"{root}/docs"
    else:
        # Replace home directory with tilde for portability
        home = str(Path.home())
        project_root_str = str(project_root)
        if project_root_str.startswith(home):
            root = project_root_str.replace(home, "~", 1)
        else:
            root = project_root_str

        snippets_root_str = str(snippets_root)
        if snippets_root_str.startswith(home):
            snippets_root_str = snippets_root_str.replace(home, "~", 1)

    payload: IndexPayload = {
        "project_root": root,
        "snippets_root": snippets_root_str,
        "snippets": snippets,
    }
    return payload


def _get_project_name(project_root: Path) -> str:
    """Get project name from directory or config."""
    # Try to get from teleclaude.yml or use directory name
    config_file = project_root / "teleclaude.yml"
    if config_file.exists():
        try:
            import yaml

            config = yaml.safe_load(config_file.read_text(encoding="utf-8"))
            if isinstance(config, dict) and "project_name" in config:
                return str(config["project_name"])
        except Exception:
            pass
    return project_root.name


def _check_global_collisions(
    snippets: list[SnippetEntry],
    project_root: Path,
    snippets_root: Path,
) -> None:
    """Check for ID collisions with global documentation.

    Only applies when building docs/global/ - checks against ~/.teleclaude/docs/index.yaml
    """
    # Only check if this is a global docs root
    try:
        rel_path = snippets_root.relative_to(project_root)
        if str(rel_path) != "docs/global" and "agents/docs" not in str(rel_path):
            # Not global docs, no collision check needed
            return
    except ValueError:
        # snippets_root not under project_root
        return

    # Check if we're building baseline docs (special case - no collision check)
    if "baseline" in str(project_root):
        return

    global_index_path = Path.home() / ".teleclaude" / "docs" / "index.yaml"
    if not global_index_path.exists():
        # No existing global index, no collisions possible
        return

    try:
        import yaml

        global_data = yaml.safe_load(global_index_path.read_text(encoding="utf-8"))
    except Exception:
        # Can't read global index, skip collision check
        return

    if not isinstance(global_data, dict) or "snippets" not in global_data:
        return

    # Build lookup of existing global snippets
    global_snippets = {}
    for entry in global_data["snippets"]:
        if isinstance(entry, dict):
            snippet_id = entry.get("id")
            source_project = entry.get("source_project", "unknown")
            if snippet_id:
                global_snippets[snippet_id] = source_project

    # Check for collisions
    current_project = _get_project_name(project_root)
    collisions = []

    for snippet in snippets:
        snippet_id = snippet["id"]
        if snippet_id in global_snippets:
            owner = global_snippets[snippet_id]
            if owner != current_project:
                collisions.append((snippet_id, owner, snippet.get("path", "")))

    if collisions:
        error_msg = ["", "=" * 80, "ERROR: Global snippet ID collision(s) detected", "=" * 80, ""]
        for snippet_id, owner, path in collisions:
            error_msg.extend(
                [
                    f"ID: {snippet_id}",
                    f"Your project: {current_project}",
                    f"Already owned by: {owner}",
                    f"Your file: {path}",
                    "",
                    "INSTRUCTIONS:",
                    f"1. Read the existing snippet in ~/.teleclaude/docs/ with ID '{snippet_id}'",
                    "2. If it already contains your information: just reference it, don't duplicate",
                    "3. If it doesn't contain your information:",
                    "   - Investigate whether to merge your content (coordinate with owner)",
                    "   - Or use a more specific ID (e.g., add domain/project prefix)",
                    "   - Or rename if they're actually different concepts",
                    "",
                    "-" * 80,
                    "",
                ]
            )
        error_msg.append("=" * 80)
        raise SystemExit("\n".join(error_msg))


def write_index_yaml(project_root: Path, snippets_root: Path) -> Path:
    target = snippets_root / "index.yaml"
    if "third-party" in snippets_root.parts:
        if target.exists():
            target.unlink()
        return target
    payload = build_index_payload(project_root, snippets_root)
    # Note: build_index_payload now returns portable paths with tilde by default
    if not payload["snippets"]:
        if target.exists():
            target.unlink()
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    rendered = yaml.safe_dump(payload, sort_keys=False, allow_unicode=False)
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if existing == rendered:
            return target
    target.write_text(rendered, encoding="utf-8")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Build snippet indexes with portable paths.")
    parser.add_argument("--project-root", default=str(Path.cwd()), help="Project root (default: cwd)")
    parser.add_argument(
        "--warn-only",
        action="store_true",
        help="Best-effort mode: report warnings but do not exit non-zero.",
    )
    args = parser.parse_args()
    global _LOG_WARNINGS
    if args.warn_only:
        _LOG_WARNINGS = False

    project_root = Path(args.project_root).expanduser().resolve()
    _ensure_project_config(project_root)
    _validate_third_party_docs(project_root)
    _write_third_party_index(project_root)
    roots = _iter_snippet_roots(project_root)
    if not roots:
        logger.info("no_snippet_roots", project_root=str(project_root))
        return
    written: list[Path] = []
    for snippets_root in roots:
        written.append(write_index_yaml(project_root, snippets_root))
    for path in written:
        logger.info("index_written", path=str(path))
        if not args.warn_only:
            print(str(path))
    warn_only = args.warn_only
    if _WARNINGS:
        print(f"Snippet validation warnings: {len(_WARNINGS)}")
        grouped: dict[str, list[dict[str, str]]] = {}
        for warning in _WARNINGS:
            grouped.setdefault(warning["code"], []).append(warning)
        for code, items in grouped.items():
            reason_groups: dict[str, list[str]] = {}
            no_reason: list[str] = []
            for warning in items:
                path = warning.get("path", "")
                if not path:
                    continue
                reason = warning.get("reason")
                if reason:
                    reason_groups.setdefault(reason, []).append(path)
                else:
                    no_reason.append(path)
            if no_reason:
                print(f"{code}:")
                for path in no_reason:
                    print(f"- {path}")
            for reason, paths in reason_groups.items():
                if not paths:
                    continue
                print(f"{code}/{reason}:")
                for path in paths:
                    print(f"- {path}")
        if not warn_only:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
