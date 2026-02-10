#!/usr/bin/env -S uv run --quiet
"""Markdown linter for TeleClaude documentation.

Validates:
- Mermaid diagram syntax
- Frontmatter completeness and correctness (for docs with frontmatter)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Mapping

import frontmatter

# Allow repo imports for shared validation utilities.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from teleclaude.constants import TAXONOMY_TYPES  # noqa: E402
from teleclaude.snippet_validation import (  # noqa: E402
    expected_snippet_id_for_path,
    load_domains,
    validate_snippet_id_format,
)

# Directories to scan for markdown files
MARKDOWN_DIRS = [
    "docs",  # Main documentation
    "agents/docs",  # Agent-specific docs
    "todos",  # Active work items
    "ideas",  # Feature ideas and proposals
    "docs-3rd",  # Third-party research
]

# Root-level markdown files to validate
ROOT_MARKDOWN_FILES = ["README.md", "AGENTS.md"]


def _validate_mermaid_diagrams(file_path: Path, content: str) -> list[str]:
    """Validate Mermaid diagram syntax.

    Returns:
        List of error messages (empty if valid)
    """
    errors: list[str] = []

    # Extract mermaid blocks
    mermaid_blocks = re.findall(r"```mermaid\n(.*?)```", content, re.DOTALL)

    for idx, block in enumerate(mermaid_blocks, start=1):
        # Check for common syntax errors

        # 1. Parentheses in square-bracket node labels (causes parse errors)
        # Pattern: [text (with parens)] but NOT ["text (with parens)"]
        # Match square brackets that contain parens but NOT if the content starts with a quote
        if re.search(r"\[(?![\"\'])[^\]]*\([^\)]*\)", block):
            errors.append(
                f"{file_path}:{_find_line_number(content, block)} "
                f"Mermaid diagram {idx}: Parentheses inside square brackets. "
                'Use quotes instead: ["Text (with parens)"]'
            )

        # 2. Missing or invalid diagram type
        first_line = block.strip().split("\n")[0]
        valid_types = [
            "graph",
            "flowchart",
            "sequenceDiagram",
            "classDiagram",
            "stateDiagram",
            "erDiagram",
            "gantt",
            "pie",
            "journey",
        ]
        if not any(first_line.startswith(t) for t in valid_types):
            errors.append(
                f"{file_path}:{_find_line_number(content, block)} "
                f"Mermaid diagram {idx}: Invalid or missing diagram type "
                f'(first line: "{first_line[:50]}")'
            )

        # 3. Using \n instead of <br/> in node labels (doesn't render properly)
        if re.search(r"\[.*\\n.*\]", block):
            errors.append(
                f"{file_path}:{_find_line_number(content, block)} "
                f"Mermaid diagram {idx}: Use <br/> instead of \\n in node labels"
            )

    return errors


def _find_line_number(content: str, block: str) -> int:
    """Find approximate line number of a block in content."""
    try:
        pos = content.index(block)
        return content[:pos].count("\n") + 1
    except ValueError:
        return 0


def _validate_frontmatter(file_path: Path, metadata: Mapping[str, object], *, domains: set[str]) -> list[str]:
    """Validate frontmatter completeness and correctness.

    Returns:
        List of error messages (empty if valid)
    """
    errors: list[str] = []

    # Required fields for snippets (docs with frontmatter)
    required = ["id", "description", "type", "scope"]
    for field in required:
        value = metadata.get(field)
        if not isinstance(value, str):
            errors.append(f"{file_path}: Missing or invalid '{field}' in frontmatter")

    # Validate type against taxonomy
    valid_types = list(TAXONOMY_TYPES)
    snippet_type = metadata.get("type")
    if isinstance(snippet_type, str) and snippet_type not in valid_types:
        errors.append(f"{file_path}: Invalid type '{snippet_type}'. Must be one of: {', '.join(valid_types)}")

    # Validate scope
    valid_scopes = ["global", "domain", "project"]
    scope = metadata.get("scope")
    if isinstance(scope, str) and scope not in valid_scopes:
        errors.append(f"{file_path}: Invalid scope '{scope}'. Must be one of: {', '.join(valid_scopes)}")

    snippet_id = metadata.get("id")
    if isinstance(snippet_id, str):
        parsed_id, id_error = validate_snippet_id_format(snippet_id, domains=domains)
        if id_error:
            errors.append(f"{file_path}: Invalid snippet id '{snippet_id}' ({id_error})")
        expected_id, path_error = expected_snippet_id_for_path(file_path, project_root=REPO_ROOT, domains=domains)
        if path_error:
            errors.append(f"{file_path}: Invalid doc path ({path_error})")
        elif expected_id and parsed_id and parsed_id.value() != expected_id:
            errors.append(f"{file_path}: Snippet id '{snippet_id}' does not match path '{expected_id}'")

    return errors


def _find_markdown_files(repo_root: Path) -> list[Path]:
    """Find all markdown files to validate."""
    files: list[Path] = []

    # Root-level markdown
    for pattern in ROOT_MARKDOWN_FILES:
        path = repo_root / pattern
        if path.exists():
            files.append(path)

    # Documentation directories
    for doc_dir in MARKDOWN_DIRS:
        doc_path = repo_root / doc_dir
        if doc_path.exists():
            files.extend(doc_path.rglob("*.md"))

    return sorted(files)


def main() -> int:
    """Run markdown validation.

    Returns:
        0 if all validations pass, 1 if errors found
    """
    repo_root = REPO_ROOT
    markdown_files = _find_markdown_files(repo_root)
    domains = load_domains(repo_root)

    if not markdown_files:
        return 0

    all_errors: list[str] = []

    for file_path in markdown_files:
        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            all_errors.append(f"{file_path}: Failed to read file: {exc}")
            continue

        # Validate Mermaid diagrams (all markdown files)
        mermaid_errors = _validate_mermaid_diagrams(file_path, text)
        all_errors.extend(mermaid_errors)

        # Validate frontmatter (only for files that have it)
        if text.lstrip().startswith("---"):
            try:
                post = frontmatter.loads(text)
                metadata: Mapping[str, object] = post.metadata or {}

                # Only validate frontmatter for snippet docs (skip baseline, README, etc.)
                # Baseline docs don't have frontmatter by design
                if "baseline" not in str(file_path) and metadata:
                    frontmatter_errors = _validate_frontmatter(file_path, metadata, domains=domains)
                    all_errors.extend(frontmatter_errors)
            except Exception as exc:
                all_errors.append(f"{file_path}: Failed to parse frontmatter: {exc}")

    if all_errors:
        print("\n❌ Markdown validation failed:\n", file=sys.stderr)
        for error in all_errors:
            print(f"  {error}", file=sys.stderr)
        print(file=sys.stderr)
        return 1

    print("✓ Markdown validation passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
