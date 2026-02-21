# Implementation Plan: tui-todo-dependencies

## Overview

Thread `after` (dependencies) and `group` fields from `RoadmapEntry` through the 6-layer data pipeline to the TUI. Each layer is a simple field addition following existing patterns. No architectural changes needed.

The data already exists in `RoadmapEntry` (core/next_machine/core.py:701) but is dropped at the `list_todos()` boundary (core/command_handlers.py:669). This plan adds the fields at each layer.

## Phase 1: Data Pipeline

### Task 1.1: Add `after` and `group` to `TodoInfo`

**File(s):** `teleclaude/core/models.py`

- [x] Add `after: List[str] = field(default_factory=list)` after `files` (line 1027)
- [x] Add `group: Optional[str] = None` after `after`
- [x] Update `from_dict()` to parse both fields with safe defaults

### Task 1.2: Pass fields through `list_todos()`

**File(s):** `teleclaude/core/command_handlers.py`

- [x] Add `after` and `group` parameters to `append_todo()` (line 610)
- [x] Pass them to `TodoInfo` constructor (line 624)
- [x] Update call site (line 669): `append_todo(slug, description=entry.description, after=entry.after, group=entry.group)`

### Task 1.3: Add `after` and `group` to `TodoDTO`

**File(s):** `teleclaude/api_models.py`

- [x] Add `after: list[str] = Field(default_factory=list)` after `files` (line 192)
- [x] Add `group: str | None = None` after `after`

### Task 1.4: Pass fields in API serialization

**File(s):** `teleclaude/api_server.py`

- [ ] Add `after=t.after, group=t.group` to `TodoDTO` construction at line 1129 (no-cache fallback)
- [ ] Add `after=todo.after, group=todo.group` to `TodoDTO` construction at line 1160 (cache path)

## Phase 2: TUI Display

### Task 2.1: Add `after` and `group` to `TodoItem`

**File(s):** `teleclaude/cli/tui/todos.py`

- [ ] Add `after: list[str] = field(default_factory=list)` after `files` (line 22)
- [ ] Add `group: str | None = None` after `after`

### Task 2.2: Pass fields in PreparationView and add group headers

**File(s):** `teleclaude/cli/tui/views/preparation.py`

- [ ] Add `after=getattr(t, "after", [])` to TodoItem construction (line 104)
- [ ] Add `group=getattr(t, "group", None)` to TodoItem construction
- [ ] Track current group per project; insert `GroupSeparator` when group changes

### Task 2.3: Display dependencies in TodoRow

**File(s):** `teleclaude/cli/tui/widgets/todo_row.py`

- [ ] After property columns (line 196), append dimmed dependency suffix:
  ```python
  if self.todo.after:
      dep_text = ", ".join(self.todo.after)
      line.append(f"  \u2190 {dep_text}", style=_DIM)
  ```

---

## Phase 3: Validation

### Task 3.1: Tests

- [ ] Run `pytest tests/unit/test_cache.py tests/unit/test_api_server.py tests/unit/test_mcp_server.py -x`
- [ ] Verify no regressions in existing tests

### Task 3.2: Manual Verification

- [ ] Restart daemon: `make restart`
- [ ] SIGUSR2 reload TUI: `pkill -SIGUSR2 -f -- "-m teleclaude.cli.telec$"`
- [ ] Open TUI Preparation tab: verify group headers and dependency arrows
- [ ] Curl check: `curl -s --unix-socket /tmp/teleclaude-api.sock http://localhost/todos | python -m json.tool` - verify `after` and `group` fields

### Task 3.3: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 4: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
