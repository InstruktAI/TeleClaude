#!/usr/bin/env -S uv run --quiet
"""Markdown linter for TeleClaude documentation.

Validates:
- Mermaid diagram syntax
- Frontmatter completeness and correctness (for docs with frontmatter)
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

# Allow repo imports for shared validation utilities.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from teleclaude.docs_publishers import DocsPublisherResolutionError, publisher_resolution
from teleclaude.paths import is_platform_home
from teleclaude.resource_validation import _error, clear_errors, get_errors, validate_all_snippets
from teleclaude.resource_validation._markdown import markdown_read_scope, parse_markdown, read_markdown

# Directories to scan for markdown files
MARKDOWN_DIRS = [
    "docs",  # Main documentation
    "agents/docs",  # Agent-specific docs
    "todos",  # Active work items
    "docs-3rd",  # Third-party research
]
AGENT_ARTIFACT_DIRS = (
    Path("agents/global/commands"),
    Path("agents/global/skills"),
    Path("agents/local/commands"),
    Path("agents/local/skills"),
)

# Root-level markdown files to validate
ROOT_MARKDOWN_FILES = ["README.md", "AGENTS.md"]
_CONTENT_ROOT_FLAG = "--content-root"
_PLATFORM_HOME_SUBJECT_FLAG = "--platform-home-subject"
_SKIP_SNIPPETS_FLAG = "--skip-snippets"
_NO_FILES_FLAG = "--no-files"
_FULL_RUN_FLAG = "--full-run"
_CONTENT_ROOT_REQUIRES_PATHS = "Content-root snippet validation requires explicit file paths."
_PATH_SEPARATOR = os.sep
_EMPTY_STRING = ""
_FINDING_PATH_FIELD = "path"
_FINDING_CODE_FIELD = "code"
_FINDING_NON_DISPLAY_FIELDS = frozenset({_FINDING_CODE_FIELD, _FINDING_PATH_FIELD})
_FINDING_WITH_EXTRAS = "{code}: {path} ({extras})"
_FINDING_WITHOUT_EXTRAS = "{code}: {path}"
_FINDING_EXTRA_SEPARATOR = ", "
_PATHS_ARGUMENT = "paths"
_ARGPARSE_STORE_TRUE = "store_true"
_ARGPARSE_ZERO_OR_MORE = "*"


@dataclass(frozen=True)
class _Arguments:
    """Parsed markdown-linter arguments."""

    paths: list[str]
    content_root: Path | None
    platform_home_subject: bool
    skip_snippets: bool
    no_files: bool
    full_run: bool


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


def _format_validation_finding(finding: Mapping[str, str], *, content_root: Path | None = None) -> str:
    formatted = dict(finding)
    if content_root is not None:
        root = content_root.resolve()
        path = Path(finding[_FINDING_PATH_FIELD])
        try:
            relative_path = path.resolve().relative_to(root).as_posix()
        except ValueError:
            relative_path = finding[_FINDING_PATH_FIELD]
        prefix = f"{root}{_PATH_SEPARATOR}"
        formatted = {key: value.replace(prefix, _EMPTY_STRING) for key, value in finding.items()}
        formatted[_FINDING_PATH_FIELD] = relative_path
    finding = formatted
    extras = _FINDING_EXTRA_SEPARATOR.join(
        f"{key}={value}" for key, value in finding.items() if key not in _FINDING_NON_DISPLAY_FIELDS
    )
    if extras:
        return _FINDING_WITH_EXTRAS.format(
            code=finding[_FINDING_CODE_FIELD],
            path=finding[_FINDING_PATH_FIELD],
            extras=extras,
        )
    return _FINDING_WITHOUT_EXTRAS.format(
        code=finding[_FINDING_CODE_FIELD],
        path=finding[_FINDING_PATH_FIELD],
    )


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
            text = read_markdown(file_path)
        except Exception as exc:
            all_errors.append(f"{file_path}: Failed to read file: {exc}")
            continue

        mermaid_errors = _validate_mermaid_diagrams(file_path, text)
        all_errors.extend(mermaid_errors)

        if text.lstrip().startswith("---") and not _is_agent_artifact(file_path, repo_root):
            try:
                post = parse_markdown(text)
                metadata: Mapping[str, object] = post.metadata or {}
                if "baseline" not in str(file_path) and metadata:
                    frontmatter_errors = _validate_frontmatter(file_path, metadata)
                    all_errors.extend(frontmatter_errors)
            except Exception as exc:
                all_errors.append(f"{file_path}: Failed to parse frontmatter: {exc}")
    return all_errors


def _validate_snippets(
    repo_root: Path,
    *,
    paths: list[Path] | None = None,
    content_root: Path | None = None,
    platform_home_subject: bool = False,
    full_run: bool = False,
) -> list[str]:
    """Run the snippet reader over publisher sources; it needs no documentation lease.

    The platform home's own tier roots (companies/people) join the walk only
    when this run's repository root is the home itself — the home's commit
    gate is this validator's guardrails leg. Every other repository's run
    passes no tier home, so a malformed or uncommitted home tier file never
    reaches an unrelated repository's run.
    """
    clear_errors()
    validation_root = content_root.resolve() if content_root is not None else repo_root
    if content_root is not None and paths is None:
        raise ValueError(_CONTENT_ROOT_REQUIRES_PATHS)
    tier_home = (
        validation_root if platform_home_subject or (content_root is None and is_platform_home(repo_root)) else None
    )
    validation_paths = (
        [validation_root / path.resolve().relative_to(repo_root.resolve()) for path in paths]
        if content_root is not None and paths is not None
        else paths
    )
    try:
        with publisher_resolution(validation_root):
            validate_all_snippets(validation_root, paths=validation_paths, tier_home=tier_home, full_run=full_run)
    except DocsPublisherResolutionError as exc:
        _error("snippet_global_source_resolution_failed", path=str(validation_root), reason=str(exc))
    return [_format_validation_finding(finding, content_root=content_root) for finding in get_errors()]


def _parse_arguments(argv: list[str]) -> _Arguments:
    """Parse file targets and optional staged-content validation settings."""
    parser = argparse.ArgumentParser()
    parser.add_argument(_CONTENT_ROOT_FLAG, type=Path)
    parser.add_argument(_PLATFORM_HOME_SUBJECT_FLAG, action=_ARGPARSE_STORE_TRUE)
    parser.add_argument(_SKIP_SNIPPETS_FLAG, action=_ARGPARSE_STORE_TRUE)
    parser.add_argument(_NO_FILES_FLAG, action=_ARGPARSE_STORE_TRUE)
    parser.add_argument(_FULL_RUN_FLAG, action=_ARGPARSE_STORE_TRUE)
    parser.add_argument(_PATHS_ARGUMENT, nargs=_ARGPARSE_ZERO_OR_MORE)
    parsed = parser.parse_args(argv)
    return _Arguments(
        paths=parsed.paths,
        content_root=parsed.content_root,
        platform_home_subject=parsed.platform_home_subject,
        skip_snippets=parsed.skip_snippets,
        no_files=parsed.no_files,
        full_run=parsed.full_run,
    )


def main() -> int:
    """Run all Markdown predicates against one invocation's source images."""
    with markdown_read_scope():
        return _main()


def _main() -> int:
    """Run markdown validation.

    When file paths are provided as argv, validates only those files (scoped).
    With no args, validates repo-wide (full-run fallback for --all / CI).

    Returns:
        0 if all validations pass, 1 if errors found
    """
    repo_root = Path.cwd().resolve()

    arguments = _parse_arguments(sys.argv[1:])
    file_args = arguments.paths
    if arguments.no_files and not file_args:
        return 0
    if arguments.content_root is not None and not file_args:
        print(_CONTENT_ROOT_REQUIRES_PATHS, file=sys.stderr)
        return 1
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
        if not arguments.skip_snippets:
            all_errors.extend(
                _validate_snippets(
                    repo_root,
                    paths=resolved,
                    content_root=arguments.content_root,
                    platform_home_subject=arguments.platform_home_subject,
                    full_run=arguments.full_run,
                )
            )
    else:
        markdown_files_list = _find_markdown_files(repo_root)
        if not markdown_files_list:
            return 0

        all_errors = _validate_files(markdown_files_list, repo_root)
        if not arguments.skip_snippets:
            all_errors.extend(_validate_snippets(repo_root))

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
