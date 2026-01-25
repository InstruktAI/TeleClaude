#!/usr/bin/env -S uv run --quiet
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Mapping, TypedDict

import frontmatter
import yaml
from instrukt_ai_logging import get_logger

# Allow running from any working directory by anchoring imports at repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

logger = get_logger(__name__)
_WARNINGS: list[dict[str, str]] = []

_REQUIRED_READS_HEADER = re.compile(r"^##\s+Required reads\s*$", re.IGNORECASE)
_HEADER_LINE = re.compile(r"^#{1,6}\s+")
_REQUIRED_READ_LINE = re.compile(r"^\s*-\s*@(\S+)\s*$")
_H1_LINE = re.compile(r"^#\s+")
_H2_LINE = re.compile(r"^##\s+")
_INLINE_REF_LINE = re.compile(r"^\\s*(?:-\\s*)?@\\S+")

_SCHEMA_PATH = Path(__file__).resolve().parent / "snippet_schema.yaml"


def _teleclaude_root(keep_tilde: bool) -> str:
    """Return teleclaude root path. Expands ~ by default."""
    if keep_tilde:
        return "~/.teleclaude"
    return str(Path.home() / ".teleclaude")


def _get_allowed_ref_prefixes(keep_tilde: bool) -> tuple[str, str]:
    """Return allowed reference prefixes, optionally expanding tilde."""
    root = _teleclaude_root(keep_tilde)
    return (f"@{root}/docs/", "@docs/")


class GlobalSchemaConfig(TypedDict, total=False):
    required_reads_title: str
    see_also_title: str
    require_h1: bool
    require_h1_first: bool
    require_required_reads: bool
    required_reads_header_level: int
    see_also_header_level: int
    allow_h3: bool


class SectionSchema(TypedDict):
    required: list[str]
    allowed: list[str]


class SchemaConfig(TypedDict):
    global_: GlobalSchemaConfig
    sections: dict[str, SectionSchema]


_TYPE_SUFFIX = {
    "policy": "Policy",
    "procedure": "Procedure",
    "reference": "Reference",
    "principles": "Principle",
    "principle": "Principle",
    "standard": "Standard",
    "guide": "Guide",
    "checklist": "Checklist",
    "role": "Role",
    "concept": "Concept",
    "architecture": "Architecture",
    "example": "Example",
    "decision": "Decision",
    "incident": "Incident",
    "timeline": "Timeline",
    "faq": "FAQ",
}


def _resolve_requires(
    file_path: Path,
    requires: list[str],
    snippets_root: Path,
    project_root: Path,
    snippet_path_to_id: dict[str, str],
) -> list[str]:
    resolved: list[str] = []
    for req in requires:
        if not isinstance(req, str):
            continue
        # If requires already looks like a snippet id, keep it.
        if not req.endswith(".md"):
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
                resolved.append(str(absolute))
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


def _warn(code: str, path: str, **kwargs: str) -> None:
    payload = {"code": code, "path": path}
    payload.update({k: str(v) for k, v in kwargs.items()})
    _WARNINGS.append(payload)
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


def _normalize_titles(snippets_root: Path, keep_tilde: bool) -> None:
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
        _validate_snippet_format(path, full_content, keep_tilde)


def _validate_snippet_format(path: Path, content: str, keep_tilde: bool) -> None:
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
    for idx, line in enumerate(lines):
        if _REQUIRED_READS_HEADER.match(line):
            required_reads_found = True
            required_reads_header_idx = idx
            break
    if _SCHEMA["global_"].get("require_required_reads", True):
        if not required_reads_found:
            _warn("snippet_required_reads_missing", path=str(path))
        if required_reads_found and required_reads_header_idx is not None:
            if not lines[required_reads_header_idx].startswith("## "):
                _warn("snippet_required_reads_header_level", path=str(path))
            h2_indices = [i for i, line in enumerate(lines) if _H2_LINE.match(line)]
            if h2_indices and h2_indices[0] != required_reads_header_idx:
                _warn("snippet_required_reads_not_first_h2", path=str(path))

    h2_titles: list[str] = []
    for line in lines:
        if _H2_LINE.match(line):
            h2_titles.append(line.lstrip("#").strip())
    normalized_titles = [_normalize_section_title(t) for t in h2_titles]

    if "see also" in normalized_titles:
        last_h2 = normalized_titles[-1] if normalized_titles else ""
        if last_h2 != "see also":
            _warn("snippet_see_also_not_last", path=str(path))

    allowed_prefixes = _get_allowed_ref_prefixes(keep_tilde)
    for line in lines:
        if not _INLINE_REF_LINE.match(line):
            continue
        ref = line.strip().lstrip("-").strip()
        if not ref.startswith(allowed_prefixes):
            _warn("snippet_invalid_inline_ref", path=str(path), ref=ref)

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
            if title in ("required reads", "see also"):
                continue
            if title not in allowed:
                _warn("snippet_unknown_section", path=str(path), section=title)


class SnippetEntry(TypedDict):
    id: str
    description: str
    type: str
    scope: str
    path: str
    requires: list[str]


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
    candidates = [project_root / "agents" / "docs", project_root / "docs"]
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


def _write_baseline_index(project_root: Path, keep_tilde: bool) -> None:
    baseline_root = project_root / "agents" / "docs" / "baseline"
    if not baseline_root.exists():
        return
    root = _teleclaude_root(keep_tilde)
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
            "# Baseline Index — Index",
            "",
            "## Required reads",
            "",
            *entries,
            "",
        ]
    )
    baseline_index.write_text(content, encoding="utf-8")


def build_index_payload(project_root: Path, snippets_root: Path, keep_tilde: bool) -> IndexPayload:
    violations = _strip_baseline_frontmatter(project_root)
    if violations:
        logger.warning("baseline_frontmatter_removed", paths=violations)
        print("Unexpected baseline frontmatter was found and cleaned.")
    _write_baseline_index(project_root, keep_tilde)
    _normalize_titles(snippets_root, keep_tilde)
    if not snippets_root.exists():
        return {
            "project_root": str(project_root),
            "snippets": [],
        }

    snippet_path_to_id: dict[str, str] = {}
    snippet_cache: list[tuple[Path, Mapping[str, object]]] = []
    snippet_files = sorted(_snippet_files(snippets_root))
    if not snippet_files:
        return {
            "project_root": str(project_root),
            "snippets": [],
        }
    for file_path in snippet_files:
        post = frontmatter.load(file_path)
        metadata: Mapping[str, object] = post.metadata or {}
        snippet_id = metadata.get("id")
        if isinstance(snippet_id, str):
            snippet_path_to_id[str(file_path.relative_to(snippets_root))] = snippet_id
        snippet_cache.append((file_path, metadata))

    snippets: list[SnippetEntry] = []
    for file_path, metadata in snippet_cache:
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
        requires_list = _extract_required_reads(post.content)
        requires = _resolve_requires(file_path, requires_list, snippets_root, project_root, snippet_path_to_id)
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
            "requires": requires,
        }
        snippets.append(entry)

    snippets.sort(key=lambda entry: entry["id"])
    payload: IndexPayload = {
        "project_root": str(project_root),
        "snippets": snippets,
    }
    _detect_cycles(payload)
    return payload


def _detect_cycles(payload: IndexPayload) -> None:
    graph: dict[str, list[str]] = {}
    for entry in payload.get("snippets", []):
        graph[entry["id"]] = list(entry.get("requires", []))

    visited: set[str] = set()
    in_stack: set[str] = set()
    stack: list[str] = []

    def visit(node: str) -> None:
        if node in in_stack:
            idx = stack.index(node) if node in stack else 0
            cycle = stack[idx:] + [node]
            _warn(
                "snippet_circular_reference",
                cycle=" -> ".join(cycle),
                hint="Fix circular references first.",
            )
            return
        if node in visited:
            return
        visited.add(node)
        in_stack.add(node)
        stack.append(node)
        for nxt in graph.get(node, []):
            if nxt in graph:
                visit(nxt)
        stack.pop()
        in_stack.remove(node)

    for node in graph:
        visit(node)


def write_index_yaml(project_root: Path, snippets_root: Path, keep_tilde: bool) -> Path:
    target = snippets_root / "index.yaml"
    payload = build_index_payload(project_root, snippets_root, keep_tilde)
    if snippets_root == project_root / "agents" / "docs" and project_root == REPO_ROOT:
        root = _teleclaude_root(keep_tilde)
        payload["project_root"] = root
        payload["snippets_root"] = f"{root}/docs"
        for snippet in payload["snippets"]:
            if snippet["path"].startswith("agents/docs/"):
                snippet["path"] = snippet["path"].replace("agents/docs/", "docs/", 1)
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
    parser = argparse.ArgumentParser(description="Build snippet indexes from docs/ and agents/docs/.")
    parser.add_argument("--project-root", default=str(Path.cwd()), help="Project root (default: cwd)")
    parser.add_argument(
        "--keep-tilde",
        action="store_true",
        help="Keep ~ notation instead of expanding to absolute HOME path (default: expand)",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    _ensure_project_config(project_root)
    roots = _iter_snippet_roots(project_root)
    if not roots:
        logger.info("no_snippet_roots", project_root=str(project_root))
        return
    written: list[Path] = []
    for snippets_root in roots:
        written.append(write_index_yaml(project_root, snippets_root, args.keep_tilde))
    for path in written:
        logger.info("index_written", path=str(path))
        print(str(path))
    if _WARNINGS:
        print(f"Snippet validation warnings: {len(_WARNINGS)}")
        for warning in _WARNINGS:
            details = " ".join(f"{k}={v}" for k, v in warning.items() if k not in {"code"})
            print(f"- {warning['code']} {details}".strip())
        if not os.getenv("TELECLAUDE_DOCS_AUTOMATION"):
            raise SystemExit(1)


if __name__ == "__main__":
    main()
