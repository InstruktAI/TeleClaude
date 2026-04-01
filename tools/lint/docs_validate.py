#!/usr/bin/env python3
"""Validate staged docs snippets and agent artifacts for pre-commit."""

from __future__ import annotations

import sys
from pathlib import Path

import frontmatter

from teleclaude.resource_validation import (
    clear_errors,
    get_errors,
    validate_all_artifacts,
    validate_artifact,
)
from teleclaude.resource_validation._snippet import validate_all_snippets, validate_snippet
from teleclaude.snippet_validation import load_domains

_FULL_REPO_INPUTS = {
    "scripts/snippet_schema.yaml",
    "teleclaude/constants.py",
}


def _normalize_paths(repo_root: Path, raw_paths: list[str]) -> list[str]:
    """Normalize raw path arguments to repo-relative POSIX paths."""
    normalized: list[str] = []
    for raw in raw_paths:
        candidate = Path(raw)
        try:
            resolved = (
                candidate.resolve(strict=False)
                if candidate.is_absolute()
                else (repo_root / candidate).resolve(strict=False)
            )
            rel = resolved.relative_to(repo_root).as_posix()
        except ValueError:
            continue
        normalized.append(rel)
    return normalized


def _artifact_kind(rel_path: str) -> str | None:
    """Return the artifact kind for a repo-relative agent path."""
    if rel_path.startswith(("agents/commands/", ".agents/commands/")) and rel_path.endswith(".md"):
        return "command"
    if rel_path.startswith(("agents/agents/", ".agents/agents/")) and rel_path.endswith(".md"):
        return "agent"
    if rel_path.startswith(("agents/skills/", ".agents/skills/")) and rel_path.endswith("/SKILL.md"):
        return "skill"
    return None


def _requires_full_repo_validation(rel_path: str) -> bool:
    """Return True when a changed file affects validation globally."""
    if rel_path in _FULL_REPO_INPUTS:
        return True
    return rel_path.startswith(("agents/", ".agents/")) and _artifact_kind(rel_path) is None


def _format_validation_record(record: dict[str, str]) -> str:
    """Format a structured warning/error payload for stdout."""
    extras = ", ".join(f"{key}={value}" for key, value in record.items() if key not in {"code", "path"})
    if extras:
        return f"{record['code']}: {record['path']} ({extras})"
    return f"{record['code']}: {record['path']}"


def _print_diagnostics(extra_errors: list[str]) -> int:
    """Print accumulated validation errors, return exit code."""
    structured_errors = get_errors()

    for message in extra_errors:
        print(message)
    for error_record in structured_errors:
        print(_format_validation_record(error_record))

    return 1 if extra_errors or structured_errors else 0


def main(argv: list[str] | None = None) -> int:
    """Validate the provided staged docs/artifact paths."""
    repo_root = Path(__file__).resolve().parents[2]
    raw_paths = list(sys.argv[1:] if argv is None else argv)
    selected_paths = _normalize_paths(repo_root, raw_paths)

    if not selected_paths:
        return 0

    clear_errors()
    extra_errors: list[str] = []

    if any(_requires_full_repo_validation(rel_path) for rel_path in selected_paths):
        extra_errors.extend(validate_all_artifacts(repo_root))
        validate_all_snippets(repo_root)
        return _print_diagnostics(extra_errors)

    domains = load_domains(repo_root)
    for rel_path in selected_paths:
        path = repo_root / rel_path
        if not path.is_file():
            continue

        if rel_path.startswith("docs/") and rel_path.endswith(".md"):
            try:
                content = path.read_text(encoding="utf-8")
            except OSError as exc:
                extra_errors.append(f"{rel_path}: {exc}")
                continue
            validate_snippet(path, content, repo_root, domains=domains)
            continue

        artifact_kind = _artifact_kind(rel_path)
        if artifact_kind is None:
            continue

        try:
            with open(path, encoding="utf-8") as handle:
                post = frontmatter.load(handle)
            validate_artifact(post, str(path), kind=artifact_kind, project_root=repo_root)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            extra_errors.append(str(exc))

    return _print_diagnostics(extra_errors)


if __name__ == "__main__":
    raise SystemExit(main())
