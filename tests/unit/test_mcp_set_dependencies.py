"""Unit tests for set_dependencies validation logic.

Tests validation rules (tested directly, not via MCP):
1. Circular dependency detection works correctly
2. Dependency read/write functions work correctly
"""

import json
import tempfile
from pathlib import Path

from teleclaude.core.next_machine import (
    detect_circular_dependency,
    read_dependencies,
    write_dependencies,
)


def test_detect_circular_dependency_simple_cycle() -> None:
    """Test detection of simple A -> B -> A cycle."""
    existing_deps = {"b": ["a"]}
    cycle = detect_circular_dependency(existing_deps, "a", ["b"])
    assert cycle is not None
    assert "a" in cycle and "b" in cycle


def test_detect_circular_dependency_self_reference() -> None:
    """Test detection of self-reference A -> A."""
    existing_deps: dict[str, list[str]] = {}
    cycle = detect_circular_dependency(existing_deps, "a", ["a"])
    assert cycle is not None
    assert "a" in cycle


def test_detect_circular_dependency_transitive() -> None:
    """Test detection of A -> B -> C -> A cycle."""
    existing_deps = {"b": ["c"], "c": ["a"]}
    cycle = detect_circular_dependency(existing_deps, "a", ["b"])
    assert cycle is not None
    assert "a" in cycle and "b" in cycle and "c" in cycle


def test_detect_circular_dependency_no_cycle() -> None:
    """Test that valid DAG returns None."""
    existing_deps = {"b": ["c"], "c": ["d"]}
    cycle = detect_circular_dependency(existing_deps, "a", ["b"])
    assert cycle is None


def test_read_write_dependencies_roundtrip() -> None:
    """Test that write followed by read preserves data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cwd = Path(tmpdir)
        deps_to_write = {"a": ["b", "c"], "b": ["c"]}

        write_dependencies(cwd, deps_to_write)
        deps_read = read_dependencies(cwd)

        assert deps_read == deps_to_write


def test_read_dependencies_missing_file() -> None:
    """Test that missing dependencies.json returns empty dict."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cwd = Path(tmpdir)
        deps = read_dependencies(cwd)
        assert deps == {}


def test_write_dependencies_creates_todos_dir() -> None:
    """Test that write_dependencies creates todos/ if missing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cwd = Path(tmpdir)
        write_dependencies(cwd, {"a": ["b"]})

        deps_file = cwd / "todos" / "dependencies.json"
        assert deps_file.exists()

        with open(deps_file, encoding="utf-8") as f:
            data = json.load(f)
        assert data == {"a": ["b"]}
