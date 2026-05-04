# pylint: disable=import-outside-toplevel
"""Tests for R3: language abstraction / toolchain protocol.

Behavioral contracts for the multi-language toolchain protocol: dispatch,
protocol conformance, and extensibility without dispatch changes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from teleclaude.quality.toolchain import (
    TOOLCHAIN_REGISTRY,
    TypeScriptToolchain,
    get_toolchain,
)

# ---------------------------------------------------------------------------
# R3.1 — Dispatch selects the correct toolchain by language
# ---------------------------------------------------------------------------


class TestToolchainDispatch:
    """get_toolchain returns the correct toolchain for the declared language."""

    def test_python_language_returns_python_toolchain(self, tmp_path: Path) -> None:
        """get_toolchain('python', ...) returns the Python toolchain implementation."""
        toolchain = get_toolchain("python", project_root=tmp_path)
        assert toolchain is not None
        # The toolchain name must identify it as Python
        assert "python" in type(toolchain).__name__.lower() or toolchain.language == "python"

    def test_unknown_language_raises_error(self, tmp_path: Path) -> None:
        """get_toolchain with an unknown language raises KeyError or ValueError."""
        with pytest.raises((KeyError, ValueError)):
            get_toolchain("cobol", project_root=tmp_path)


# ---------------------------------------------------------------------------
# R3.2 — Toolchain protocol conformance
# ---------------------------------------------------------------------------


class TestToolchainProtocolConformance:
    """Each toolchain implementation must expose all required protocol capabilities."""

    def test_python_toolchain_has_tools_attribute(self, tmp_path: Path) -> None:
        """Python toolchain exposes a list of available lint/check tools."""
        toolchain = get_toolchain("python", project_root=tmp_path)
        assert hasattr(toolchain, "tools"), "Toolchain must expose available tools"
        assert len(toolchain.tools) > 0, "Python toolchain must list at least one tool"

    def test_python_toolchain_has_config_source(self, tmp_path: Path) -> None:
        """Python toolchain declares its configuration source (pyproject.toml)."""
        toolchain = get_toolchain("python", project_root=tmp_path)
        assert hasattr(toolchain, "config_source"), "Toolchain must declare its config source"
        config_source = str(toolchain.config_source)
        assert "pyproject.toml" in config_source, f"Python config source must be pyproject.toml, got: {config_source}"

    def test_python_toolchain_has_test_companion_mapping(self, tmp_path: Path) -> None:
        """Python toolchain encapsulates the test companion mapping convention."""
        toolchain = get_toolchain("python", project_root=tmp_path)
        assert hasattr(toolchain, "map_to_test_companion"), "Toolchain must expose map_to_test_companion method"
        companion = toolchain.map_to_test_companion("teleclaude/foo/bar.py")
        assert companion == "tests/unit/foo/test_bar.py", (
            f"Companion mapping wrong: expected 'tests/unit/foo/test_bar.py', got {companion!r}"
        )

    def test_python_toolchain_has_source_dirs(self, tmp_path: Path) -> None:
        """Python toolchain exposes its configured source directories."""
        (tmp_path / "pyproject.toml").write_text(
            "[tool.ruff]\nsrc = ['teleclaude', 'tools', 'tests']\n",
            encoding="utf-8",
        )
        toolchain = get_toolchain("python", project_root=tmp_path)
        assert hasattr(toolchain, "source_dirs"), "Toolchain must expose source_dirs"
        source_dirs = toolchain.source_dirs
        assert len(source_dirs) > 0, "Python toolchain must resolve at least one source dir"
        # Source dirs must reflect the configuration, not hardcoded values
        source_dir_strs = [str(d) for d in source_dirs]
        assert any("teleclaude" in d for d in source_dir_strs), (
            f"source_dirs missing 'teleclaude' from pyproject.toml config: {source_dir_strs}"
        )
        assert any("tools" in d for d in source_dir_strs), (
            f"source_dirs missing 'tools' from pyproject.toml config: {source_dir_strs}"
        )


# ---------------------------------------------------------------------------
# R3.3 — Adding a new toolchain requires no dispatch changes
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# TypeScript toolchain
# ---------------------------------------------------------------------------


class TestTypeScriptToolchain:
    """TypeScript toolchain is registered and conforms to protocol."""

    def test_typescript_toolchain_registered(self, tmp_path: Path) -> None:
        """get_toolchain('typescript', ...) returns the TypeScript toolchain."""
        toolchain = get_toolchain("typescript", project_root=tmp_path)
        assert toolchain.language == "typescript"

    def test_typescript_toolchain_has_eslint_and_tsc(self, tmp_path: Path) -> None:
        """TypeScript toolchain lists eslint and tsc as tools."""
        toolchain = get_toolchain("typescript", project_root=tmp_path)
        assert "eslint" in toolchain.tools
        assert "tsc" in toolchain.tools

    def test_typescript_toolchain_has_config_source(self, tmp_path: Path) -> None:
        """TypeScript toolchain declares package.json as its config source."""
        toolchain = get_toolchain("typescript", project_root=tmp_path)
        assert "package.json" in toolchain.config_source

    def test_typescript_companion_mapping(self, tmp_path: Path) -> None:
        """TypeScript toolchain maps source to __tests__ companion."""
        toolchain = get_toolchain("typescript", project_root=tmp_path)
        companion = toolchain.map_to_test_companion("app/foo/bar.tsx")
        assert "test" in companion.lower() or "__tests__" in companion

    def test_typescript_source_dirs_contains_frontend_root_path(self, tmp_path: Path) -> None:
        """TypeScript toolchain source_dirs contains the resolved frontend_root path."""
        toolchain = TypeScriptToolchain(project_root=tmp_path, frontend_root="web")
        dirs = toolchain.source_dirs
        assert len(dirs) == 1
        assert str(tmp_path / "web") == dirs[0], f"source_dirs should contain resolved frontend_root path, got: {dirs}"

    def test_get_toolchain_passes_frontend_root_to_typescript(self, tmp_path: Path) -> None:
        """get_toolchain('typescript', ..., frontend_root='custom') propagates to source_dirs."""
        toolchain = get_toolchain("typescript", project_root=tmp_path, frontend_root="custom")
        dirs = toolchain.source_dirs
        assert str(tmp_path / "custom") == dirs[0], (
            f"get_toolchain did not pass frontend_root through — got {dirs[0]!r}, expected {str(tmp_path / 'custom')!r}"
        )


# ---------------------------------------------------------------------------
# R3.3 — Adding a new toolchain requires no dispatch changes
# ---------------------------------------------------------------------------


class TestExtensibility:
    """A new toolchain can be registered without modifying dispatch logic."""

    def test_custom_toolchain_registered_and_dispatched(self, tmp_path: Path) -> None:
        """A custom toolchain registered in TOOLCHAIN_REGISTRY is reachable via get_toolchain."""

        class _FakeToolchain:  # pylint: disable=too-few-public-methods
            """Minimal protocol-conforming toolchain for registry dispatch test."""

            language = "fake-lang"
            tools: list[str] = ["fake-linter"]
            config_source = "fake.toml"

            def map_to_test_companion(self, source: str) -> str:
                """Map source to fake test companion path."""
                return f"fake_tests/{source}"

            @property
            def source_dirs(self) -> list[str]:
                """Return fake source directories."""
                return ["fake_src"]

        original_registry = dict(TOOLCHAIN_REGISTRY)
        try:
            TOOLCHAIN_REGISTRY["fake-lang"] = lambda _root: _FakeToolchain()
            toolchain = get_toolchain("fake-lang", project_root=tmp_path)
            assert toolchain is not None
            assert toolchain.language == "fake-lang"
        finally:
            TOOLCHAIN_REGISTRY.clear()
            TOOLCHAIN_REGISTRY.update(original_registry)
