#!/usr/bin/env -S uv run --quiet
from __future__ import annotations

import argparse
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
        absolute = (file_path.parent / req).resolve()
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


def build_index_payload(project_root: Path, snippets_root: Path) -> IndexPayload:
    violations = _strip_baseline_frontmatter(project_root)
    if violations:
        logger.warning("baseline_frontmatter_removed", paths=violations)
        print("Unexpected baseline frontmatter was found and cleaned.")
    if not snippets_root.exists():
        return {
            "project_root": str(project_root),
            "snippets_root": str(snippets_root),
            "snippets": [],
        }

    snippet_path_to_id: dict[str, str] = {}
    snippet_cache: list[tuple[Path, Mapping[str, object]]] = []
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
        requires_raw = metadata.get("requires", [])
        requires_list = requires_raw if isinstance(requires_raw, list) else []
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
        "snippets_root": str(snippets_root),
        "snippets": snippets,
    }
    return payload


def write_index_yaml(project_root: Path, snippets_root: Path) -> Path:
    target = snippets_root / "index.yaml"
    payload = build_index_payload(project_root, snippets_root)
    if not payload["snippets"]:
        if target.exists():
            target.unlink()
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=False)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Build snippet indexes from docs/ and agents/docs/.")
    parser.add_argument("--project-root", default=str(Path.cwd()), help="Project root (default: cwd)")
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    _ensure_project_config(project_root)
    roots = _iter_snippet_roots(project_root)
    if not roots:
        logger.info("no_snippet_roots", project_root=str(project_root))
        return
    written: list[Path] = []
    for snippets_root in roots:
        written.append(write_index_yaml(project_root, snippets_root))
    for path in written:
        logger.info("index_written", path=str(path))
        print(str(path))


if __name__ == "__main__":
    main()
