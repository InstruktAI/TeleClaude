from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import cast


def _load_exclusions(repo_root: Path) -> set[str]:
    """Load excluded paths from pyproject.toml [tool.test-mapping].exclude."""
    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.exists():
        print(f"ERROR: pyproject.toml not found: {pyproject_path}", file=sys.stderr)
        sys.exit(2)
    with open(pyproject_path, "rb") as f:
        data_obj = tomllib.load(f)
    if not isinstance(data_obj, dict):
        return set()
    data = cast(dict[str, object], data_obj)
    tool_obj = data.get("tool")
    if not isinstance(tool_obj, dict):
        return set()
    tool = cast(dict[str, object], tool_obj)
    mapping_obj = tool.get("test-mapping")
    if not isinstance(mapping_obj, dict):
        return set()
    mapping = cast(dict[str, object], mapping_obj)
    exclude_obj = mapping.get("exclude")
    if not isinstance(exclude_obj, list):
        return set()
    return {item for item in exclude_obj if isinstance(item, str)}


def _mirror_path(source_path: str) -> str:
    """Compute the expected test path for a source path.

    Replaces the ``teleclaude/`` prefix with ``tests/unit/`` and renames
    ``<name>.py`` to ``test_<name>.py``.
    """
    without_prefix = source_path.removeprefix("teleclaude/")
    parent, filename = without_prefix.rsplit("/", 1) if "/" in without_prefix else ("", without_prefix)
    test_filename = f"test_{filename}"
    if parent:
        return f"tests/unit/{parent}/{test_filename}"
    return f"tests/unit/{test_filename}"


def main(repo_root: Path | None = None) -> None:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]

    teleclaude_root = repo_root / "teleclaude"
    if not teleclaude_root.is_dir():
        print(f"ERROR: source directory not found: {teleclaude_root}", file=sys.stderr)
        sys.exit(2)

    source_files: list[str] = [
        path.relative_to(repo_root).as_posix()
        for path in teleclaude_root.rglob("*.py")
        if path.name != "__init__.py" and "__pycache__" not in path.parts
    ]
    source_files.sort()

    exclusions: set[str] = _load_exclusions(repo_root)

    gaps: list[tuple[str, str]] = []
    for source_path in source_files:
        if source_path in exclusions:
            continue
        mirrored = _mirror_path(source_path)
        if not (repo_root / mirrored).exists():
            gaps.append((source_path, mirrored))

    if gaps:
        print("MISSING TEST COVERAGE:")
        max_src = max(len(src) for src, _ in gaps)
        for src, test_path in gaps:
            print(f"  {src:<{max_src}} → {test_path}")
        print()
        print(f"Total: {len(gaps)} unmapped source files (see pyproject.toml [tool.test-mapping].exclude to exempt)")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
