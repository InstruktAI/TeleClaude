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
def test_build_dep_tree_renders_group_children_before_after_sorted_roots() -> None:
    nodes = build_dep_tree(
        [
            _todo("a"),
            _todo("b", group="a"),
            _todo("c", after=["a"]),
        ]
    )

    assert [(node.slug, node.depth, node.is_last, node.tree_lines) for node in nodes] == [
        ("a", 0, False, []),
        ("b", 1, True, [True]),
        ("c", 0, True, []),
    ]


@pytest.mark.unit
def test_topo_sort_siblings_falls_back_to_input_order_for_cycles_and_external_dependencies() -> None:
    assert _topo_sort_siblings(["x", "y"], {"x": ["y"], "y": ["x"]}) == ["x", "y"]
    assert _topo_sort_siblings(["x", "y"], {"x": ["outside"]}) == ["x", "y"]
