from __future__ import annotations

import pytest

from teleclaude.cli.tui.prep_tree import _topo_sort_siblings, build_dep_tree
from teleclaude.cli.tui.todos import TodoItem, TodoStatus


def _todo(slug: str, *, group: str | None = None, after: list[str] | None = None) -> TodoItem:
    return TodoItem(
        slug=slug,
        status=TodoStatus.PENDING,
        description=None,
        has_requirements=True,
        has_impl_plan=True,
        group=group,
        after=after or [],
    )


@pytest.mark.unit
def test_after_only_items_cascade_under_their_first_visible_dep() -> None:
    """When `group` is absent, `after` drives visual nesting under the first
    resolvable dep, so dependency chains render as a cascade."""
    nodes = build_dep_tree(
        [
            _todo("a"),
            _todo("b", group="a"),
            _todo("c", after=["a"]),
        ]
    )

    assert [(node.slug, node.depth, node.is_last, node.tree_lines) for node in nodes] == [
        ("a", 0, True, []),
        ("b", 1, False, [True]),
        ("c", 1, True, [True]),
    ]


@pytest.mark.unit
def test_explicit_group_beats_after_for_hierarchy() -> None:
    """When `group` and `after` disagree, explicit `group` wins (tso-* case):
    item declares membership in test-suite-overhaul while listing
    refactor-large-files as a dep — it must nest under the group, not the dep."""
    nodes = build_dep_tree(
        [
            _todo("refactor-large-files"),
            _todo("test-suite-overhaul"),
            _todo("tso-foo", group="test-suite-overhaul", after=["refactor-large-files"]),
        ]
    )
    assert [(node.slug, node.depth) for node in nodes] == [
        ("refactor-large-files", 0),
        ("test-suite-overhaul", 0),
        ("tso-foo", 1),
    ]


@pytest.mark.unit
def test_after_cascade_picks_first_visible_entry() -> None:
    """Multi-parent after=[A, B] nests under A (first). Cross-group after still
    influences root ordering (Phase 2) but only one parent is drawn."""
    nodes = build_dep_tree(
        [
            _todo("a"),
            _todo("b"),
            _todo("c", after=["a", "b"]),
        ]
    )
    # Phase 2 promotes root `a` after root `b` because c (in a's tree) depends on b.
    # c is drawn as a's child (first-in-list); the b dep is still respected via root ordering.
    assert [(node.slug, node.depth) for node in nodes] == [
        ("b", 0),
        ("a", 0),
        ("c", 1),
    ]


@pytest.mark.unit
def test_after_cycle_does_not_loop_one_item_becomes_root() -> None:
    """When two items reference each other via `after`, the first processed gets
    a parent and the second is forced to root by the cycle guard — no infinite
    recursion, predictable shape."""
    nodes = build_dep_tree(
        [
            _todo("a", after=["b"]),
            _todo("b", after=["a"]),
        ]
    )
    # Processing order: a sees no parent_map entry for b → a.parent = b.
    # Then b sees parent_map[a] = b → cycle → b stays root.
    assert [(node.slug, node.depth, node.is_last, node.tree_lines) for node in nodes] == [
        ("b", 0, True, []),
        ("a", 1, True, [True]),
    ]


@pytest.mark.unit
def test_topo_sort_siblings_falls_back_to_input_order_for_cycles_and_external_dependencies() -> None:
    assert _topo_sort_siblings(["x", "y"], {"x": ["y"], "y": ["x"]}) == ["x", "y"]
    assert _topo_sort_siblings(["x", "y"], {"x": ["outside"]}) == ["x", "y"]
