#!/usr/bin/env -S uv run --quiet
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Mapping, TypedDict, cast

import frontmatter
import yaml

from instrukt_ai_logging import get_logger
from scripts.build_snippet_index import build_index_payload

logger = get_logger(__name__)


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


def _load_index_yaml(index_path: Path) -> Mapping[str, object]:
    if not index_path.exists():
        raise FileNotFoundError(f"Index not found: {index_path}")
    with open(index_path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError("Index YAML is not a mapping")
    return cast(Mapping[str, object], data)


def _normalize_payload(payload: Mapping[str, object]) -> IndexPayload:
    snippets = payload.get("snippets", [])
    if not isinstance(snippets, list):
        snippets = []
    normalized_snippets = []
    for entry in snippets:
        if not isinstance(entry, dict):
            continue
        snippet_id = entry.get("id")
        description = entry.get("description")
        snippet_type = entry.get("type")
        snippet_scope = entry.get("scope")
        path = entry.get("path")
        requires = entry.get("requires", [])
        if (
            not isinstance(snippet_id, str)
            or not isinstance(description, str)
            or not isinstance(snippet_type, str)
            or not isinstance(snippet_scope, str)
            or not isinstance(path, str)
        ):
            continue
        requires_list = [req for req in requires if isinstance(req, str)] if isinstance(requires, list) else []
        normalized_snippets.append(
            SnippetEntry(
                id=snippet_id,
                description=description,
                type=snippet_type,
                scope=snippet_scope,
                path=path,
                requires=requires_list,
            )
        )
    normalized_snippets.sort(key=lambda entry: entry["id"])
    project_root = payload.get("project_root", "")
    payload_root = project_root if isinstance(project_root, str) else ""
    return {"project_root": payload_root, "snippets": normalized_snippets}


def validate_index(project_root: Path, index_path: Path) -> list[str]:
    errors: list[str] = []
    yaml_payload = _normalize_payload(_load_index_yaml(index_path))
    rebuilt_payload = _normalize_payload(build_index_payload(project_root))

    yaml_snippets = {entry["id"]: entry for entry in yaml_payload["snippets"]}
    rebuilt_snippets = {entry["id"]: entry for entry in rebuilt_payload["snippets"]}

    missing_ids = sorted(set(rebuilt_snippets.keys()) - set(yaml_snippets.keys()))
    extra_ids = sorted(set(yaml_snippets.keys()) - set(rebuilt_snippets.keys()))
    changed_ids = sorted(
        snippet_id
        for snippet_id in set(yaml_snippets.keys()) & set(rebuilt_snippets.keys())
        if yaml_snippets[snippet_id] != rebuilt_snippets[snippet_id]
    )

    if missing_ids:
        errors.append(f"Missing snippets in index.yaml: {', '.join(missing_ids)}")
    if extra_ids:
        errors.append(f"Extra snippets in index.yaml: {', '.join(extra_ids)}")
    if changed_ids:
        errors.append(f"Outdated snippets in index.yaml: {', '.join(changed_ids)}")

    for entry in yaml_payload["snippets"]:
        snippet_path = project_root / entry["path"]
        if not snippet_path.exists():
            errors.append(f"Missing snippet file: {entry['path']}")
            continue
        post = frontmatter.load(snippet_path)
        metadata = post.metadata or {}
        snippet_type = metadata.get("type")
        snippet_scope = metadata.get("scope")
        if not isinstance(snippet_type, str):
            errors.append(f"Invalid type in snippet frontmatter: {entry['path']}")
        if not isinstance(snippet_scope, str):
            errors.append(f"Invalid scope in snippet frontmatter: {entry['path']}")

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate docs/index.yaml against docs/snippets.")
    parser.add_argument("--project-root", default=str(Path.cwd()), help="Project root (default: cwd)")
    parser.add_argument("--index", default=None, help="Index path (default: <project-root>/docs/index.yaml)")
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    index_path = Path(args.index).expanduser().resolve() if args.index else project_root / "docs" / "index.yaml"

    errors = validate_index(project_root, index_path)
    if errors:
        for error in errors:
            print(error)
        raise SystemExit(1)

    print("index.yaml OK")
    logger.info("index_ok", path=str(index_path))


if __name__ == "__main__":
    main()
