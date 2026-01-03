# Requirements: State Machine Refinement

## Problem Statement

The `next_work` state machine in `teleclaude/core/next_machine.py` has two issues:

1. **Bug check conflation**: `next_work()` first checks for pending bugs in `todos/bugs.md` before processing roadmap items. This conflates bug fixing with roadmap work. Bug fixing should be a separate workflow, not embedded in `next_work`.

2. **Incomplete state model**: The current roadmap uses only `[ ]` (pending) and `[>]` (in progress), but doesn't distinguish between:
   - Items that are just ideas (not prepared)
   - Items that are ready for work (prepared with requirements + implementation plan)

   This causes `next_work` to find unprepared items and error out, rather than finding the first actually-ready item.

3. **No dependency tracking**: Work items may depend on other items being completed first. Currently there's no way to express or enforce this.

4. **Manual state management**: The state machine code doesn't manage roadmap checkbox transitions - this is left to AI/humans, introducing inconsistency.

---

## Current Behavior

### `next_work()` flow (lines 628-750 in `next_machine.py`):

1. **Bug check** (lines 641-653): If no slug provided AND `todos/bugs.md` has unchecked items, dispatch `next-bugs` command
2. **Resolve slug**: Find first roadmap item (either `[ ]` or `[>]`)
3. **Error if not in progress**: If item is `[ ]`, return error suggesting `next_prepare()`
4. Continue with build/review/fix/finalize cycle

### `resolve_slug()` behavior (lines 287-336):

- Pattern matches both `[ ]` and `[>]` items: `r"^-\s+\[([ >])\]\s+(\S+)"`
- Returns the FIRST match regardless of state
- If roadmap has `[ ]` items before `[>]` items, returns the `[ ]` item

---

## Required Changes

### R1: Remove Bug Check from `next_work()`

Delete the bug check block (lines 641-653). Bug fixing is a separate workflow and should not be part of `next_work`. The `next-bugs` command and related infrastructure can remain for standalone use.

### R2: Introduce Ready State Symbol `[.]`

Add a new checkbox state to represent "prepared and ready for work":

| Symbol | Meaning | Description |
|--------|---------|-------------|
| `[ ]` | Pending | Roadmap item exists, not yet prepared (no requirements/implementation-plan) |
| `[.]` | Ready | Prepared with requirements.md and implementation-plan.md, available to be claimed |
| `[>]` | In Progress | Claimed by a worker, actively being worked on |
| `[x]` | Completed | Done (typically removed/archived by finalize) |

### R3: State Machine Owns Checkbox Transitions

The code (not AI/humans) must manage all state transitions in `roadmap.md`:

| Transition | Trigger | Responsibility |
|------------|---------|----------------|
| `[ ]` → `[.]` | `next_prepare` completes successfully (requirements.md + implementation-plan.md exist) | `next_prepare()` function |
| `[.]` → `[>]` | `next_work` claims item for execution | `next_work()` function |
| `[>]` → removed | `next_finalize` completes | Already handled by finalize command (Step 8) |

### R4: Create `todos/dependencies.json`

Introduce a machine-readable dependency graph file at `todos/dependencies.json`:

```json
{
  "user-dashboard": ["auth-system", "user-api"],
  "admin-panel": ["user-dashboard"]
}
```

Format:
- Keys: slugs that have dependencies
- Values: list of slugs that must be completed BEFORE the key can be worked on
- Items with no dependencies are not listed (or have empty array)
- File may not exist if no dependencies are declared

### R5: Add `teleclaude__set_dependencies()` Tool

Create a new MCP tool for declaring dependencies:

```python
teleclaude__set_dependencies(
    slug: str,        # The work item
    after: list[str]  # Items that must complete before this one
) -> str
```

Behavior:
- Replaces ALL dependencies for `slug` (not additive)
- `after=[]` clears all dependencies for `slug`
- Writes to `todos/dependencies.json`
- Creates file if it doesn't exist

Validation (MUST enforce):
1. `slug` must exist in `todos/roadmap.md`
2. All items in `after` must exist in `todos/roadmap.md`
3. `slug` must not be in `after` (no self-reference)
4. No circular dependencies (A depends on B depends on A)
5. Slug format: `[a-z0-9-]+` only

On validation failure: Return clear error, do NOT modify file.

### R6: Modify `resolve_slug()` for `next_work`

When called from `next_work()`, `resolve_slug()` must:

1. Only match `[.]` items (ready state), skip `[ ]` and `[>]`
2. For each `[.]` item found, check dependencies:
   - Read `todos/dependencies.json`
   - Get dependencies for this slug
   - Check if ALL dependencies are satisfied (completed/archived)
3. Return the first `[.]` item with all dependencies satisfied

An item's dependencies are satisfied when all items in its `after` list are:
- Marked as `[x]` in roadmap, OR
- Not present in roadmap (assumed completed/archived)
- Existence in `done/*-{slug}/` directory also indicates completion

### R7: Add Roadmap State Update Function

Create a function to atomically update checkbox state in `roadmap.md`:

```python
def update_roadmap_state(cwd: str, slug: str, new_state: str) -> bool:
    """Update checkbox state for slug in roadmap.md.

    Args:
        cwd: Project root
        slug: Work item slug
        new_state: One of " ", ".", ">", "x"

    Returns:
        True if updated, False if slug not found

    Side effects:
        - Modifies todos/roadmap.md
        - Commits the change to git
    """
```

---

## Validation Requirements

### Roadmap Format

Lines in `todos/roadmap.md` matching work items must follow:

```
- [STATE] slug-name
```

Where:
- `STATE` is one of: ` ` (space), `.`, `>`, `x`
- `slug-name` matches `[a-z0-9-]+`
- Description text may follow on subsequent lines (until next `- [` or `##`)

### Dependencies Format

`todos/dependencies.json` must be valid JSON with structure:

```json
{
  "slug": ["dep1", "dep2"],
  ...
}
```

---

## Edge Cases

### E1: Missing dependencies.json

If file doesn't exist, treat all items as having no dependencies (all `[.]` items are eligible).

### E2: Dependency references non-existent slug

When `teleclaude__set_dependencies()` is called with a dependency that doesn't exist in roadmap:
- Return error: `"Dependency '{dep}' not found in roadmap.md"`
- Do NOT modify dependencies.json

### E3: Stale `[>]` items

If a worker crashes mid-work, the `[>]` item remains stuck. This is intentional:
- Humans must manually reset to `[.]` if needed
- No automatic timeout/recovery (too risky)

### E4: Circular dependencies

When `teleclaude__set_dependencies()` would create a cycle:
- Detect by traversing the graph
- Return error: `"Circular dependency detected: {cycle_path}"`
- Do NOT modify dependencies.json

### E5: All ready items have unsatisfied dependencies

If all `[.]` items depend on incomplete work:
- Return error: `"No ready items with satisfied dependencies"`
- Suggest completing dependency items first

---

## Files Affected

| File | Changes |
|------|---------|
| `teleclaude/core/next_machine.py` | Remove bug check, add `update_roadmap_state()`, modify `resolve_slug()`, update `next_prepare()` to mark `[.]`, update `next_work()` to mark `[>]` |
| `teleclaude/mcp_server.py` | Add `teleclaude__set_dependencies()` tool |
| `todos/dependencies.json` | New file (created when first dependency is set) |
| `todos/roadmap.md` | Status legend update to include `[.]` |

---

## Testing Requirements

### Unit Tests

1. `test_update_roadmap_state`: Verify state transitions work correctly
2. `test_resolve_slug_ready_only`: Verify only `[.]` items are returned for next_work
3. `test_dependency_satisfaction`: Verify dependency checking logic
4. `test_set_dependencies_validation`: Verify all validation rules
5. `test_circular_dependency_detection`: Verify cycle detection works
6. `test_next_work_without_bugs`: Verify bug check is removed

### Integration Tests

1. Full cycle: `[ ]` → `[.]` → `[>]` → archived
2. Dependency blocking: Item with unsatisfied deps is skipped
3. Dependency satisfaction: Item becomes available when deps complete

---

## Out of Scope

- Race condition handling (multiple AIs claiming same item) - not a concern per user
- Automatic stale `[>]` recovery - left to humans
- Bug workflow integration - separate concern
