# Implementation Plan: new-bug-key-in-todos-pane

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the dependency tree rendering to use the `after` graph (not list order), generalize the file viewer to be path-based (not slug-scoped), add `roadmap.yaml` as the first tree entry, and add `b` keybinding for quick bug creation.

**Architecture:** The tree rendering is rebuilt from the ground up to derive structure from `after` dependencies. The file-open mechanism is changed from `(slug, filename)` to absolute filepath. Bug creation reuses `create_bug_skeleton()` from `bug-delivery-service`.

**Prerequisite:** Tasks 1-4 (tree fix, viewer, roadmap entry) have no external dependencies. Tasks 5-7 (bug creation) depend on `bug-delivery-service` being built first.

---

### Task 0: Test specification for dependency tree building

**File(s):** `tests/unit/test_prep_tree_builder.py`

**Rationale:** The tree-building logic is pure computation — flat list of TodoItems with `after` fields in, structured rendering order out. Write the tests first. Implementation (Task 1) must pass them.

**Tests:**

```python
"""Unit tests for preparation view tree building from `after` graph."""

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
    assert children[1].is_last      # b


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
```

**Return type contract:** `build_dep_tree(items: list[TodoItem]) -> list[TreeRenderNode]` where `TreeRenderNode` has: `slug`, `depth`, `is_last`, `tree_lines`, `todo` (original TodoItem).

**Implementation note:** Extract the tree-building logic from `_rebuild()` into a standalone pure function (`build_dep_tree`) so it's testable without TUI widgets. Task 1 implements this function; `_rebuild()` calls it.

**Additional tests** in `tests/unit/test_prep_file_viewer.py`:

```python
"""Unit tests for filepath-based file viewer and editor command."""


def test_editor_command_absolute_path():
    """_editor_command produces correct command from absolute filepath."""
    # Simulate the new signature: filepath in, command out
    filepath = "/home/user/project/todos/my-slug/requirements.md"
    cmd = _build_editor_command(filepath)
    assert filepath in cmd
    assert "teleclaude.cli.editor" in cmd


def test_editor_command_view_flag():
    """_editor_command includes --view flag when requested."""
    filepath = "/home/user/project/todos/roadmap.yaml"
    cmd = _build_editor_command(filepath, view=True)
    assert "--view" in cmd
    assert filepath in cmd


def test_editor_command_theme_flag():
    """_editor_command includes --theme flag when theme is set."""
    filepath = "/home/user/project/todos/roadmap.yaml"
    cmd = _build_editor_command(filepath, theme="dark")
    assert "--theme dark" in cmd


def test_file_row_standalone_no_parent_match():
    """TodoFileRow with empty owner_slug never matches a TodoRow in parent lookup."""
    from teleclaude.cli.tui.widgets.todo_file_row import TodoFileRow
    from teleclaude.cli.tui.widgets.todo_row import TodoRow

    # Standalone file row (roadmap.yaml) has owner_slug="" — no tree parent
    standalone = TodoFileRow(filepath="/project/todos/roadmap.yaml", filename="roadmap.yaml", owner_slug="")

    # A todo row always has a non-empty slug
    todo = _make_todo_row("my-todo")

    # Parent lookup walks backward through nav_items matching on slug
    nav_items = [todo, standalone]
    parent = _find_parent(nav_items, standalone)
    assert parent is None


def test_file_row_finds_owning_todo():
    """TodoFileRow with an owner_slug correctly finds its parent TodoRow in the tree."""
    from teleclaude.cli.tui.widgets.todo_file_row import TodoFileRow
    from teleclaude.cli.tui.widgets.todo_row import TodoRow

    file_row = TodoFileRow(
        filepath="/project/todos/my-todo/requirements.md",
        filename="requirements.md",
        owner_slug="my-todo",
    )
    todo = _make_todo_row("my-todo")

    nav_items = [todo, file_row]
    parent = _find_parent(nav_items, file_row)
    assert parent is todo
```

**Implementation note:** `_build_editor_command` is the pure-function extraction of `_editor_command` (or test it via the method with a minimal mock). `_find_parent` mirrors the `_find_parent_todo` logic for testability. Helper `_make_todo_row` creates a minimal TodoRow.

**Design note on `owner_slug` vs `slug`:** `TodoFileRow.slug` is renamed to `owner_slug` to separate two concerns:

- **File opening** uses `filepath` — no slug in the path computation, fully unscoped.
- **Tree ownership** uses `owner_slug` — answers "which TodoRow is my parent for expand/collapse?" This is structural tree metadata, not file-path scoping. Standalone files (e.g., `roadmap.yaml`) have `owner_slug=""` and no parent.

---

### Task 1: Build dependency tree from `after` graph in `_rebuild()`

**File(s):** `teleclaude/cli/tui/views/preparation.py` (+ new `teleclaude/cli/tui/prep_tree.py` for the pure function)

**Must pass:** All tests from Task 0.

**Problem:** The current `_rebuild()` iterates the flat list in roadmap order and draws tree connectors from sequential position + depth. Items appear nested under whatever precedes them, not under their actual `after` parent. The `after` field is the sole source of truth for tree structure — `roadmap.yaml` ordering must be irrelevant.

**Steps:**

0. Extract tree-building into a standalone pure function `build_dep_tree()` in `teleclaude/cli/tui/prep_tree.py`. This function takes `list[TodoItem]` and returns `list[TreeRenderNode]`. The `_rebuild()` method calls this function instead of computing depth/connectors inline.

1. After building `todo_by_slug` and `visible_slugs`, construct the tree from `after`:
   - For each item, resolve its parent: the first entry in `item.after` that exists in `visible_slugs`. If multiple `after` entries resolve, use the first for tree placement (the others are dependency-only, not visual parents).
   - Items with no resolvable `after` are roots.
   - Build `children_map: dict[str, list[str]]` mapping parent slug → child slugs.
   - Build `parent_map: dict[str, str | None]` mapping slug → visual parent slug.

2. Walk the tree in DFS order to produce the rendering sequence:

   ```python
   def _walk_tree(roots, children_map, todo_by_slug):
       """Yield (slug, depth, is_last_sibling, parent_slug) in DFS order."""
       def _dfs(slug, depth, is_last):
           yield (slug, depth, is_last)
           kids = children_map.get(slug, [])
           for i, kid in enumerate(kids):
               _dfs(kid, depth + 1, i == len(kids) - 1)
       for i, root in enumerate(roots):
           _dfs(root, 0, False)  # depth-0 never "last" (GroupSeparator closes)
   ```

3. Replace the current flat iteration (lines 184-225) with the DFS walk output. Compute `tree_lines` from the actual tree ancestry path, not from scanning future list items:
   - For each node, walk up its parent chain. At each ancestor level, check if the ancestor has a next sibling (i.e., is not `is_last`). That determines whether a continuation line (`│`) is drawn at that depth.

4. Preserve root ordering: roots appear in the order they come from the flat list (roadmap priority). Children under each parent also preserve their flat-list relative order.

5. Handle edge cases:
   - Circular `after` references: detect during tree build, break the cycle, treat the cycle-introducing edge as a root.
   - Item with `after: [X]` where X is not in visible_slugs: item becomes a root (depth 0).
   - Item with multiple `after` entries: first resolvable = visual parent, rest are non-visual deps.

**Verification:** Reorder items in `roadmap.yaml` (e.g., move `new-bug-key-in-todos-pane` above `bug-delivery-service`) → tree still shows it nested under `bug-delivery-service`. Items with no `after` always render at root depth.

---

### Task 2: Generalize file viewer to absolute paths

**File(s):** `teleclaude/cli/tui/views/preparation.py`, `teleclaude/cli/tui/widgets/todo_file_row.py`

**Problem:** `_editor_command(slug, filename)` hardcodes the path to `todos/{slug}/{filename}`. `TodoFileRow` stores `slug` + `filename` and the view uses these to compute paths. This prevents opening files outside slug directories (e.g., `todos/roadmap.yaml`).

**Steps:**

1. Change `_editor_command` signature to accept an absolute filepath:

   ```python
   def _editor_command(self, filepath: str, *, view: bool = False) -> str:
   ```

   Remove the slug-based path computation. Callers provide the full path.

2. Add `filepath` attribute and rename `slug` → `owner_slug` on `TodoFileRow`:

   ```python
   def __init__(self, *, filepath: str, filename: str, owner_slug: str = "", ...):
       self.filepath = filepath
       self.filename = filename
       self.owner_slug = owner_slug  # tree ownership: which TodoRow is the parent for expand/collapse. Empty for standalone files.
   ```

3. Update all `TodoFileRow` creation sites to pass `filepath` and `owner_slug`:
   - In `_rebuild()` (lines 236-237): `TodoFileRow(filepath=f"{project_path}/todos/{slug}/{filename}", filename=filename, owner_slug=slug)`
   - In `_mount_file_rows()` (line 271): same pattern.
   - Update `_find_parent_todo` to use `file_row.owner_slug` instead of `file_row.slug`.

4. Update `action_activate` (line 432-439) and `action_preview_file` (line 451-461) to use `file_row.filepath`:

   ```python
   DocEditRequest(
       doc_id=file_row.filepath,
       command=self._editor_command(file_row.filepath),
       title=f"Editing: {file_row.filename}",
   )
   ```

5. Update `action_new_todo` (line 490-497) to pass filepath to the new `_editor_command`:
   ```python
   filepath = f"{project_root}/todos/{slug}/input.md"
   command=self._editor_command(filepath),
   ```

**Verification:** All existing file-open flows still work (expand todo → click file → editor opens with correct path). The mechanism is now path-based, not slug-based.

---

### Task 3: Add `roadmap.yaml` as first tree entry

**File(s):** `teleclaude/cli/tui/views/preparation.py`

**Problem:** `roadmap.yaml` is not visible in the preparation pane. Users need to manually edit it when the roadmap drifts.

**Steps:**

1. In `_rebuild()`, after mounting the `ProjectHeader` and before iterating todo rows, create a `TodoFileRow` for `roadmap.yaml`:

   ```python
   roadmap_path = f"{project.path}/todos/roadmap.yaml"
   if Path(roadmap_path).exists():
       roadmap_row = TodoFileRow(
           filepath=roadmap_path,
           filename="roadmap.yaml",
           is_last=False,
           tree_lines=[],
       )
       widgets_to_mount.append(roadmap_row)
       self._nav_items.append(roadmap_row)
   ```

2. The `roadmap_row` has no slug and no parent todo — it's a standalone file at root level. The existing `action_activate` handles it because it checks `isinstance(item, TodoFileRow)` and uses `file_row.filepath`.

3. Tree connector: the roadmap entry renders at depth 0, before all todo nodes. Its connector is a simple `├─` (not last, because todo items follow).

**Verification:** `roadmap.yaml` appears as the first entry after the project header. Enter opens it in the editor. Space previews it.

---

### Task 4: Add `telec bugs create` CLI Subcommand

**File(s):** `teleclaude/cli/telec.py`

**Prerequisite:** `bug-delivery-service` must be built first (provides `create_bug_skeleton()` and `telec bugs` CLI surface).

**Steps:**

1. Add `create` subcommand to the existing `"bugs"` entry in `CLI_SURFACE`:
   ```python
   "create": CommandDef(
       desc="Scaffold bug files for a slug",
       args="<slug>",
       flags=[_PROJECT_ROOT_LONG],
   ),
   ```
2. Add `_handle_bugs_create()` handler:
   - Parse slug from args.
   - Resolve project root.
   - Call `create_bug_skeleton(project_root, slug, description="")`.
   - Print success message with path.
   - Handle `ValueError` and `FileExistsError` with clear error messages.
3. Wire the handler into `_handle_bugs()` router.

**Verification:** `telec bugs create test-bug` creates `todos/test-bug/bug.md` + `state.yaml`. Clean up after.

---

### Task 5: Add `b` Keybinding to TUI PreparationView

**File(s):** `teleclaude/cli/tui/views/preparation.py`

**Prerequisite:** `bug-delivery-service` must be built first.

**Steps:**

1. Add keybinding to `BINDINGS` list:
   ```python
   ("b", "new_bug", "New bug"),
   ```
2. Add `action_new_bug()` method following the same pattern as `action_new_todo()`:
   - Push `CreateBugModal()` screen (see Task 6).
   - On result, resolve project root from `_slug_to_project_path`.
   - Call `create_bug_skeleton(Path(project_root), slug, description="")`.
   - Post `DocEditRequest` with filepath to `bug.md`:
     ```python
     filepath = f"{project_root}/todos/{slug}/bug.md"
     DocEditRequest(
         doc_id=filepath,
         command=self._editor_command(filepath),
         title=f"Editing: {slug}/bug.md",
     )
     ```
   - Handle `ValueError` and `FileExistsError` with `self.app.notify()`.

**Verification:** Press `b` in TUI → modal appears → enter slug → `bug.md` opens in editor.

---

### Task 6: Create Bug Modal

**File(s):** `teleclaude/cli/tui/widgets/modals.py`

**Steps:**

1. Create `CreateBugModal` as a minimal variant of `CreateTodoModal`:
   - Same structure: slug input, `SLUG_PATTERN` validation, Enter/Esc.
   - Different title: "New Bug" instead of "New Todo".
2. The class is ~48 lines — duplication cost is minimal and the title distinction is user-facing.

**Verification:** Modal renders with "New Bug" title, validates slug, returns slug on Enter.

---

### Task 7: Validation

**Steps:**

- [ ] `make lint` passes.
- [ ] `make test` passes (existing tests unbroken).
- [ ] Tree rendering: reorder items in `roadmap.yaml` → tree structure unchanged (connectors follow `after` graph).
- [ ] Tree rendering: item with `after: [X]` where X not in roadmap → renders at root depth.
- [ ] `roadmap.yaml` appears first in tree, opens in editor on Enter, previews on Space.
- [ ] File viewer: all file nodes open uniformly regardless of path.
- [ ] Manual TUI test: `b` → enter slug → bug.md opens.
- [ ] Manual CLI test: `telec bugs create test-slug` → creates correct files.
- [ ] Edge cases: empty slug, invalid slug, duplicate slug all show errors.
- [ ] `n` key still works for normal todos (no regression).

---

## Phase 2: Quality Checks

- [ ] Run `make lint`
- [ ] Run `make test`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Requirements reflected in code changes
- [ ] Implementation tasks all marked `[x]`
- [ ] Deferrals documented if applicable
