"""Tests for teleclaude.core.next_machine.dep_graph — cycle detection."""

from __future__ import annotations

from teleclaude.core.next_machine.dep_graph import detect_circular_dependency


def test_detect_circular_dependency_returns_existing_cycle_path_shape() -> None:
    """Transitive cycle through three nodes is detected and path returned."""
    cycle = detect_circular_dependency({"b": ["a"], "c": ["b"]}, "a", ["c"])

    assert cycle == ["a", "a", "c", "b", "a"]


def test_detect_circular_dependency_returns_none_when_no_cycle() -> None:
    """No cycle when new deps don't create a loop."""
    result = detect_circular_dependency({"b": ["a"]}, "c", ["b"])

    assert result is None


def test_detect_circular_dependency_detects_direct_self_cycle() -> None:
    """Direct self-dependency is caught."""
    cycle = detect_circular_dependency({}, "a", ["a"])

    assert cycle is not None
    assert "a" in cycle
