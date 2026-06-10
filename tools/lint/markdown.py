#!/usr/bin/env -S uv run --quiet
"""Markdown linter for TeleClaude documentation.

Validates:
- Mermaid diagram syntax
- Frontmatter completeness and correctness (for docs with frontmatter)
"""

from __future__ import annotations

import re
import sys
from collections.abc import Mapping
from pathlib import Path

import frontmatter

# Allow repo imports for shared validation utilities.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from teleclaude.resource_validation import clear_errors, get_errors, validate_all_snippets

# Directories to scan for markdown files
MARKDOWN_DIRS = [
    "docs",  # Main documentation
    "agents/docs",  # Agent-specific docs
    "todos",  # Active work items
    "docs-3rd",  # Third-party research
]
AGENT_ARTIFACT_DIRS = (
    Path("agents/commands"),
    Path("agents/skills"),
)

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


def _is_agent_artifact(file_path: Path, repo_root: Path) -> bool:
    try:
        rel = file_path.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return False
    return any(rel == artifact_dir or rel.is_relative_to(artifact_dir) for artifact_dir in AGENT_ARTIFACT_DIRS)


def _validate_frontmatter(file_path: Path, metadata: Mapping[str, object]) -> list[str]:
    """Validate frontmatter completeness and correctness.

    Returns:
        List of error messages (empty if valid)
    """
    errors: list[str] = []

    # Required authored fields for snippets (docs with frontmatter).
    required = ["description"]
    for field in required:
        value = metadata.get(field)
        if not isinstance(value, str):
            errors.append(f"{file_path}: Missing or invalid '{field}' in frontmatter")

    return errors


def _format_validation_finding(finding: Mapping[str, str]) -> str:
    extras = ", ".join(f"{key}={value}" for key, value in finding.items() if key not in {"code", "path"})
    if extras:
        return f"{finding['code']}: {finding['path']} ({extras})"
    return f"{finding['code']}: {finding['path']}"


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


def _validate_files(file_paths: list[Path], repo_root: Path) -> list[str]:
    """Run per-file checks (mermaid + frontmatter) over the given file list."""
    all_errors: list[str] = []
    for file_path in file_paths:
        try:
            text = file_path.read_text(encoding="utf-8")
        except Exception as exc:
            all_errors.append(f"{file_path}: Failed to read file: {exc}")
            continue

        mermaid_errors = _validate_mermaid_diagrams(file_path, text)
        all_errors.extend(mermaid_errors)

        if text.lstrip().startswith("---") and not _is_agent_artifact(file_path, repo_root):
            try:
                post = frontmatter.loads(text)
                metadata: Mapping[str, object] = post.metadata or {}
                if "baseline" not in str(file_path) and metadata:
                    frontmatter_errors = _validate_frontmatter(file_path, metadata)
                    all_errors.extend(frontmatter_errors)
            except Exception as exc:
                all_errors.append(f"{file_path}: Failed to parse frontmatter: {exc}")
    return all_errors


def main() -> int:
    """Run markdown validation.

    When file paths are provided as argv, validates only those files (scoped).
    With no args, validates repo-wide (full-run fallback for --all / CI).

    Returns:
        0 if all validations pass, 1 if errors found
    """
    repo_root = Path.cwd().resolve()

    file_args = sys.argv[1:]
    if file_args:
        resolved: list[Path] = []
        for arg in file_args:
            p = Path(arg)
            if not p.is_absolute():
                p = (repo_root / p).resolve()
            if p.exists() and p.suffix == ".md":
                resolved.append(p)
        if not resolved:
            return 0

        all_errors = _validate_files(resolved, repo_root)
        clear_errors()
        validate_all_snippets(repo_root, paths=resolved)
        all_errors.extend(_format_validation_finding(finding) for finding in get_errors())
    else:
        markdown_files_list = _find_markdown_files(repo_root)
        if not markdown_files_list:
            return 0

        all_errors = _validate_files(markdown_files_list, repo_root)
        clear_errors()
        validate_all_snippets(repo_root)
        all_errors.extend(_format_validation_finding(finding) for finding in get_errors())

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
