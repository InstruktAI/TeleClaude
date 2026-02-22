"""Unit tests for preparation view tree building from `after` graph."""

from teleclaude.cli.tui.prep_tree import build_dep_tree

from teleclaude.cli.tui.todos import TodoItem
from teleclaude.cli.tui.types import TodoStatus


def _item(slug: str, after: list[str] | None = None) -> TodoItem:
    """Minimal TodoItem for tree tests."""
    return TodoItem(
        slug=slug,
        status=TodoStatus.PENDING,
        description=None,
        has_requirements=False,
        has_impl_plan=False,
        after=after or [],
    )


def test_all_roots_no_deps():
    """Items with no `after` are all roots, in original order."""
    items = [_item("a"), _item("b"), _item("c")]
    result = build_dep_tree(items)
    assert [r.slug for r in result] == ["a", "b", "c"]
    assert all(r.depth == 0 for r in result)


def test_single_parent_child():
    """Item with after=[X] nests under X regardless of list position."""
    items = [_item("child", after=["parent"]), _item("parent")]
    result = build_dep_tree(items)
    slugs = [r.slug for r in result]
    assert slugs == ["parent", "child"]
    assert result[0].depth == 0
    assert result[1].depth == 1


def test_order_irrelevant():
    """Scrambled roadmap order doesn't affect tree structure."""
    order_a = [_item("parent"), _item("child", after=["parent"])]
    order_b = [_item("child", after=["parent"]), _item("parent")]
    result_a = [(r.slug, r.depth) for r in build_dep_tree(order_a)]
    result_b = [(r.slug, r.depth) for r in build_dep_tree(order_b)]
    assert result_a == result_b


def test_unresolvable_after_becomes_root():
    """Item with after=[nonexistent] renders at root depth."""
    items = [_item("orphan", after=["ghost"])]
    result = build_dep_tree(items)
    assert result[0].slug == "orphan"
    assert result[0].depth == 0


def test_multi_level_nesting():
    """Grandchild nests under child under parent."""
    items = [
        _item("grandchild", after=["child"]),
        _item("parent"),
        _item("child", after=["parent"]),
    ]
    result = build_dep_tree(items)
    assert [(r.slug, r.depth) for r in result] == [
        ("parent", 0),
        ("child", 1),
        ("grandchild", 2),
    ]


def test_siblings_preserve_relative_order():
    """Children of the same parent keep their original list order."""
    items = [_item("b", after=["root"]), _item("root"), _item("a", after=["root"])]
    result = build_dep_tree(items)
    # b appeared before a in original list → b first under root
    children = [r for r in result if r.depth == 1]
    assert [c.slug for c in children] == ["b", "a"]


def test_multiple_after_first_resolvable_is_visual_parent():
    """First resolvable after entry = visual parent."""
    items = [_item("parent1"), _item("parent2"), _item("child", after=["parent1", "parent2"])]
    result = build_dep_tree(items)
    # child nests under parent1 (first resolvable), not parent2
    assert [(r.slug, r.depth) for r in result] == [
        ("parent1", 0),
        ("child", 1),
        ("parent2", 0),
    ]


def test_circular_after_does_not_infinite_loop():
    """Circular deps are broken — no hang, both items render."""
    items = [_item("a", after=["b"]), _item("b", after=["a"])]
    result = build_dep_tree(items)
    slugs = {r.slug for r in result}
    assert slugs == {"a", "b"}


def test_is_last_sibling():
    """Last child of a parent has is_last=True."""
    items = [_item("root"), _item("a", after=["root"]), _item("b", after=["root"])]
    result = build_dep_tree(items)
    children = [r for r in result if r.depth == 1]
    assert not children[0].is_last  # a
    assert children[1].is_last  # b


def test_tree_lines_continuation():
    """tree_lines correctly indicate ancestor continuation."""
    items = [
        _item("root"),
        _item("child1", after=["root"]),
        _item("child2", after=["root"]),
        _item("grandchild", after=["child1"]),
    ]
    result = build_dep_tree(items)
    gc = next(r for r in result if r.slug == "grandchild")
    # grandchild is at depth 2. tree_lines[0] = True (root line continues because child2 follows)
    # tree_lines[1] depends on whether child1 has a next sibling at depth 1
    assert len(gc.tree_lines) == 2
    assert gc.tree_lines[0] is True  # root-level continuation (child2 exists)
