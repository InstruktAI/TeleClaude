"""Paranoid tests for set_dependencies validation logic.

Tests validation rules (tested directly, not via MCP):
1. Circular dependency detection works correctly
2. Dependency read/write functions work correctly
3. MCP tool validation (slug format, roadmap presence)
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core.next_machine import (
    detect_circular_dependency,
    load_roadmap_deps,
    save_roadmap,
)
from teleclaude.core.next_machine.core import RoadmapEntry
from teleclaude.mcp_server import TeleClaudeMCPServer


def _write_roadmap_yaml(tmpdir: str | Path, slugs: list[str], deps: dict[str, list[str]] | None = None) -> None:
    """Helper to write roadmap.yaml fixtures in tests."""
    entries = [RoadmapEntry(slug=s, after=(deps or {}).get(s, [])) for s in slugs]
    save_roadmap(str(tmpdir), entries)


def test_detect_circular_dependency_simple_cycle() -> None:
    """Paranoid test detection of simple A -> B -> A cycle."""
    existing_deps = {"b": ["a"]}
    cycle = detect_circular_dependency(existing_deps, "a", ["b"])
    assert cycle is not None
    assert "a" in cycle and "b" in cycle


def test_detect_circular_dependency_self_reference() -> None:
    """Paranoid test detection of self-reference A -> A."""
    existing_deps: dict[str, list[str]] = {}
    cycle = detect_circular_dependency(existing_deps, "a", ["a"])
    assert cycle is not None
    assert "a" in cycle


def test_detect_circular_dependency_transitive() -> None:
    """Paranoid test detection of A -> B -> C -> A cycle."""
    existing_deps = {"b": ["c"], "c": ["a"]}
    cycle = detect_circular_dependency(existing_deps, "a", ["b"])
    assert cycle is not None
    assert "a" in cycle and "b" in cycle and "c" in cycle


def test_detect_circular_dependency_no_cycle() -> None:
    """Paranoid test that valid DAG returns None."""
    existing_deps = {"b": ["c"], "c": ["d"]}
    cycle = detect_circular_dependency(existing_deps, "a", ["b"])
    assert cycle is None


def test_save_and_load_roadmap_deps_roundtrip() -> None:
    """Paranoid test that save followed by load preserves dependency data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        deps_to_write = {"a": ["b", "c"], "b": ["c"]}
        _write_roadmap_yaml(tmpdir, ["a", "b", "c"], deps_to_write)

        deps_read = load_roadmap_deps(str(tmpdir))
        assert deps_read == deps_to_write


def test_load_roadmap_deps_missing_file() -> None:
    """Paranoid test that missing roadmap.yaml returns empty dict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        deps = load_roadmap_deps(str(tmpdir))
        assert deps == {}


def test_save_roadmap_creates_todos_dir() -> None:
    """Paranoid test that save_roadmap creates todos/ if missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _write_roadmap_yaml(tmpdir, ["a", "b"], {"a": ["b"]})

        roadmap_file = Path(tmpdir) / "todos" / "roadmap.yaml"
        assert roadmap_file.exists()


# =============================================================================
# MCP Tool Validation Tests (R5)
# =============================================================================


@pytest.mark.asyncio
async def test_mcp_set_dependencies_invalid_slug_format() -> None:
    """Paranoid test that MCP tool rejects invalid slug format."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cwd = Path(tmpdir)

        # Create roadmap with valid slugs
        _write_roadmap_yaml(tmpdir, ["valid-slug", "another-slug"])

        # Create MCP server with mocked dependencies
        mock_client = MagicMock()
        mock_tmux_bridge = MagicMock()
        mcp = TeleClaudeMCPServer(adapter_client=mock_client, tmux_bridge=mock_tmux_bridge)

        # Test invalid slug with uppercase
        result = await mcp.teleclaude__set_dependencies("Invalid-Slug", [], cwd=str(cwd))
        assert "ERROR: INVALID_SLUG" in result
        assert "lowercase alphanumeric" in result

        # Test invalid slug with special characters
        result = await mcp.teleclaude__set_dependencies("slug_with_underscore", [], cwd=str(cwd))
        assert "ERROR: INVALID_SLUG" in result

        # Test invalid dependency format
        result = await mcp.teleclaude__set_dependencies("valid-slug", ["Invalid-Dep"], cwd=str(cwd))
        assert "ERROR: INVALID_DEP" in result


@pytest.mark.asyncio
async def test_mcp_set_dependencies_slug_not_in_roadmap() -> None:
    """Paranoid test that MCP tool rejects slug not found in roadmap."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cwd = Path(tmpdir)

        _write_roadmap_yaml(tmpdir, ["existing-slug", "another-slug"])

        # Create MCP server with mocked dependencies
        mock_client = MagicMock()
        mock_tmux_bridge = MagicMock()
        mcp = TeleClaudeMCPServer(adapter_client=mock_client, tmux_bridge=mock_tmux_bridge)

        # Test slug not in roadmap
        result = await mcp.teleclaude__set_dependencies("nonexistent-slug", [], cwd=str(cwd))
        assert "ERROR: SLUG_NOT_FOUND" in result
        assert "not found in roadmap" in result


@pytest.mark.asyncio
async def test_mcp_set_dependencies_dependency_not_in_roadmap() -> None:
    """Paranoid test that MCP tool rejects dependency not found in roadmap."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cwd = Path(tmpdir)

        _write_roadmap_yaml(tmpdir, ["item-a", "item-b"])

        # Create MCP server with mocked dependencies
        mock_client = MagicMock()
        mock_tmux_bridge = MagicMock()
        mcp = TeleClaudeMCPServer(adapter_client=mock_client, tmux_bridge=mock_tmux_bridge)

        # Test dependency not in roadmap
        result = await mcp.teleclaude__set_dependencies("item-a", ["nonexistent-dep"], cwd=str(cwd))
        assert "ERROR: DEP_NOT_FOUND" in result
        assert "not found in roadmap" in result


@pytest.mark.asyncio
async def test_mcp_set_dependencies_self_reference_via_tool() -> None:
    """Paranoid test that MCP tool rejects self-reference."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cwd = Path(tmpdir)

        _write_roadmap_yaml(tmpdir, ["item-a"])

        # Create MCP server with mocked dependencies
        mock_client = MagicMock()
        mock_tmux_bridge = MagicMock()
        mcp = TeleClaudeMCPServer(adapter_client=mock_client, tmux_bridge=mock_tmux_bridge)

        # Test self-reference
        result = await mcp.teleclaude__set_dependencies("item-a", ["item-a"], cwd=str(cwd))
        assert "ERROR: SELF_REFERENCE" in result
        assert "cannot depend on itself" in result


@pytest.mark.asyncio
async def test_mcp_set_dependencies_circular_via_tool() -> None:
    """Paranoid test that MCP tool detects circular dependencies."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cwd = Path(tmpdir)

        _write_roadmap_yaml(tmpdir, ["item-a", "item-b", "item-c"])

        # Create MCP server with mocked dependencies
        mock_client = MagicMock()
        mock_tmux_bridge = MagicMock()
        mcp = TeleClaudeMCPServer(adapter_client=mock_client, tmux_bridge=mock_tmux_bridge)

        # Set up: b depends on c
        await mcp.teleclaude__set_dependencies("item-b", ["item-c"], cwd=str(cwd))

        # Set up: c depends on a
        await mcp.teleclaude__set_dependencies("item-c", ["item-a"], cwd=str(cwd))

        # Test: trying to make a depend on b (creates cycle a -> b -> c -> a)
        result = await mcp.teleclaude__set_dependencies("item-a", ["item-b"], cwd=str(cwd))
        assert "ERROR: CIRCULAR_DEP" in result
        assert "Circular dependency detected" in result
