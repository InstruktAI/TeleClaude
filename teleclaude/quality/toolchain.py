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
class LintToolchain(Protocol):
    """Protocol for language-specific lint/test toolchain capabilities."""

    language: str
    tools: list[str]
    config_source: str

    def map_to_test_companion(self, source: str) -> str:
        """Map a source file path to its test companion path."""
        ...

    @property
    def source_dirs(self) -> list[str]:
        """Configured source directories for this language toolchain."""
        ...


class PythonToolchain:
    """Python language toolchain — ruff, pyright, mypy, jscpd."""

    language: str = "python"
    tools: list[str] = ["ruff", "pyright", "mypy", "jscpd"]
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


class TypeScriptToolchain:
    """TypeScript language toolchain — eslint, tsc."""

    language: str = "typescript"
    tools: list[str] = ["eslint", "tsc"]
    config_source: str = "package.json"

    def __init__(self, project_root: Path, frontend_root: str = "frontend") -> None:
        self._project_root = project_root
        self._frontend_root = project_root / frontend_root

    def map_to_test_companion(self, source: str) -> str:
        """Map app/foo/bar.tsx to app/foo/__tests__/bar.test.tsx."""
        parts = source.rsplit("/", 1)
        if len(parts) == 1:
            name, ext = _split_ts_ext(parts[0])
            return f"__tests__/{name}.test{ext}"
        dirname, filename = parts
        name, ext = _split_ts_ext(filename)
        return f"{dirname}/__tests__/{name}.test{ext}"

    @property
    def source_dirs(self) -> list[str]:
        """Return the frontend root as the source directory."""
        return [str(self._frontend_root)]


class RustToolchain:
    """Rust language toolchain — cargo, rustfmt, clippy."""

    language: str = "rust"
    tools: list[str] = ["cargo", "rustfmt", "clippy"]
    config_source: str = "Cargo.toml"

    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    def map_to_test_companion(self, source: str) -> str:
        """Rust tests are Cargo-scoped; no Python companion path is fabricated."""
        _ = source
        return ""

    @property
    def source_dirs(self) -> list[str]:
        """Return the Cargo workspace source root."""
        if (self._project_root / "crates").exists():
            return ["crates"]
        return ["."]


def _split_ts_ext(filename: str) -> tuple[str, str]:
    """Split a TypeScript filename into (name, extension)."""
    for ext in (".tsx", ".ts", ".jsx", ".js"):
        if filename.endswith(ext):
            return filename[: -len(ext)], ext
    return filename, ""


TOOLCHAIN_REGISTRY: dict[str, Callable[..., LintToolchain]] = {
    "python": PythonToolchain,
    "rust": RustToolchain,
    "typescript": TypeScriptToolchain,
}


def get_toolchain(language: str, project_root: Path, **kwargs: str) -> LintToolchain:
    """Look up and instantiate the toolchain for the given language.

    Extra keyword arguments (e.g. ``frontend_root``) are forwarded to the
    factory when the toolchain accepts them.

    Raises KeyError for unregistered languages.
    """
    factory = TOOLCHAIN_REGISTRY.get(language)
    if factory is None:
        raise KeyError(f"No toolchain registered for language: {language!r}")
    return factory(project_root, **kwargs)
