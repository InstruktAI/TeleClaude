#!/usr/bin/env -S uv run --quiet
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Mapping, TypedDict

import frontmatter
import yaml

from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


def _resolve_requires(file_path: Path, requires: list[str], project_root: Path) -> list[str]:
    resolved: list[str] = []
    for req in requires:
        if not isinstance(req, str):
            continue
        absolute = (file_path.parent / req).resolve()
        try:
            resolved.append(str(absolute.relative_to(project_root)))
        except ValueError:
            resolved.append(str(absolute))
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
    snippets: list[SnippetEntry]


def build_index_payload(project_root: Path) -> IndexPayload:
    docs_snippets = project_root / "docs" / "snippets"
    if not docs_snippets.exists():
        return {"project_root": str(project_root), "snippets": []}

    snippets: list[SnippetEntry] = []
    for file_path in sorted(docs_snippets.rglob("*.md")):
        if "baseline" in str(file_path):
            continue
        post = frontmatter.load(file_path)
        metadata: Mapping[str, object] = post.metadata or {}
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
        requires = _resolve_requires(file_path, requires_list, project_root)
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
    payload: IndexPayload = {"project_root": str(project_root), "snippets": snippets}
    return payload


def write_index_yaml(project_root: Path, output_path: Path | None = None) -> Path:
    target = output_path or (project_root / "docs" / "index.yaml")
    payload = build_index_payload(project_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=False)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Build docs/index.yaml from docs/snippets.")
    parser.add_argument("--project-root", default=str(Path.cwd()), help="Project root (default: cwd)")
    parser.add_argument("--output", default=None, help="Output path (default: <project-root>/docs/index.yaml)")
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve() if args.output else None
    written = write_index_yaml(project_root, output_path=output_path)
    logger.info("index_written", path=str(written))
    print(str(written))


if __name__ == "__main__":
    main()
