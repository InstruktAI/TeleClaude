#!/usr/bin/env -S uv run --quiet
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Mapping, NotRequired, TypedDict, cast

import frontmatter
import yaml
from instrukt_ai_logging import get_logger

# Allow running from any working directory by anchoring imports at repo root.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from scripts.sync_resources import (
    _collect_inline_ref_errors,
    _iter_snippet_roots,
    _validate_third_party_docs,
    _write_third_party_index,
    build_index_payload,
)
from teleclaude.snippet_validation import load_domains

logger = get_logger(__name__)


class SnippetEntry(TypedDict):
    id: str
    description: str
    type: str
    scope: str
    path: str
    requires: NotRequired[list[str]]


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


def validate_index(project_root: Path, snippets_root: Path, index_path: Path) -> list[str]:
    errors: list[str] = []
    domains = load_domains(project_root)
    yaml_payload = _normalize_payload(_load_index_yaml(index_path))
    rebuilt_payload = _normalize_payload(build_index_payload(project_root, snippets_root))

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
        raw = snippet_path.read_text(encoding="utf-8")
        post = frontmatter.loads(raw) if raw.lstrip().startswith("---") else frontmatter.Post(content=raw)
        metadata = post.metadata or {}
        snippet_type = metadata.get("type")
        snippet_scope = metadata.get("scope")
        if not isinstance(snippet_type, str):
            errors.append(f"Invalid type in snippet frontmatter: {entry['path']}")
        if not isinstance(snippet_scope, str):
            errors.append(f"Invalid scope in snippet frontmatter: {entry['path']}")
        lines = post.content.splitlines()
        for error in _collect_inline_ref_errors(project_root, snippet_path, lines, domains=domains):
            details = " ".join(f"{k}={v}" for k, v in error.items() if k != "code")
            errors.append(f"{error['code']} {details}".strip())

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate snippet indexes for docs/ and agents/docs/.")
    parser.add_argument("--project-root", default=str(Path.cwd()), help="Project root (default: cwd)")
    args = parser.parse_args()

    project_root = Path(args.project_root).expanduser().resolve()
    _validate_third_party_docs(project_root)
    _write_third_party_index(project_root)
    roots = _iter_snippet_roots(project_root)
    if not roots:
        logger.info("no_snippet_roots", project_root=str(project_root))
        return

    all_errors: list[str] = []
    for snippets_root in roots:
        index_path = snippets_root / "index.yaml"
        if not index_path.exists():
            all_errors.append(f"Missing snippet index: {index_path}")
            continue
        errors = validate_index(project_root, snippets_root, index_path)
        all_errors.extend(errors)

    if all_errors:
        for error in all_errors:
            print(error)
        raise SystemExit(1)

    print("index.yaml OK")
    for snippets_root in roots:
        logger.info("index_ok", path=str(snippets_root / "index.yaml"))


if __name__ == "__main__":
    main()
