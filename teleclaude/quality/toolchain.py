"""Language toolchain protocol and registry for multi-language quality tooling.

Defines the LintToolchain protocol, the PythonToolchain implementation,
and the extensible TOOLCHAIN_REGISTRY for dispatch-by-language.
"""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class LintToolchain(Protocol):  # pylint: disable=too-few-public-methods
    """Protocol for language-specific lint/test toolchain capabilities."""

    language: str
    tools: list[str]
    config_source: str

    def map_to_test_companion(self, source: str) -> str:
        """Map a source file path to its test companion path."""
        ...  # pylint: disable=unnecessary-ellipsis

    @property
    def source_dirs(self) -> list[str]:
        """Configured source directories for this language toolchain."""
        ...  # pylint: disable=unnecessary-ellipsis


class PythonToolchain:
    """Python language toolchain — ruff, pyright, mypy, pylint."""

    language: str = "python"
    tools: list[str] = ["ruff", "pyright", "mypy", "pylint"]
    config_source: str = "pyproject.toml"

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    def map_to_test_companion(self, source: str) -> str:
        """Map teleclaude/x/y.py to tests/unit/x/test_y.py."""
        parts = source.split("/")
        if len(parts) < 2:
            return f"tests/unit/test_{parts[0]}"
        # Strip leading package directory, prepend tests/unit/, prefix filename with test_
        subpath = parts[1:]
        subpath[-1] = f"test_{subpath[-1]}"
        return "tests/unit/" + "/".join(subpath)

    @property
    def source_dirs(self) -> list[str]:
        """Read source directories from [tool.ruff].src in pyproject.toml."""
        pyproject = self._project_root / "pyproject.toml"
        if pyproject.exists():
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            src = data.get("tool", {}).get("ruff", {}).get("src", [])
            if src:
                return list(src)
        return ["teleclaude"]


TOOLCHAIN_REGISTRY: dict[str, Callable[[Path], LintToolchain]] = {
    "python": PythonToolchain,
}


def get_toolchain(language: str, project_root: Path) -> LintToolchain:
    """Look up and instantiate the toolchain for the given language.

    Raises KeyError for unregistered languages.
    """
    factory = TOOLCHAIN_REGISTRY.get(language)
    if factory is None:
        raise KeyError(f"No toolchain registered for language: {language!r}")
    return factory(project_root)
