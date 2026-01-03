# Implementation Plan: State Machine Refinement

## Prerequisites

Before starting, read these files in order:
1. `todos/state-machine-refinement/requirements.md` - Full requirements
2. `teleclaude/core/next_machine.py` - Main file to modify
3. `teleclaude/mcp_server.py` - Tool registration
4. `~/.agents/commands/next-prepare.md` - Understand next-prepare workflow
5. `~/.agents/commands/next-finalize.md` - Understand finalize workflow

---

## Task Groups

### Group 1: Core Infrastructure

- [x] **1.1** Add `update_roadmap_state()` function to `next_machine.py`
- [x] **1.2** Add `read_dependencies()` function to `next_machine.py`
- [x] **1.3** Add `write_dependencies()` function to `next_machine.py`
- [x] **1.4** Add `check_dependencies_satisfied()` function to `next_machine.py`
- [x] **1.5** Add `detect_circular_dependency()` function to `next_machine.py`

### Group 2: Modify Existing Functions

- [x] **2.1** Remove bug check from `next_work()` (delete lines 641-653)
- [x] **2.2** Modify `resolve_slug()` to accept `ready_only` parameter
- [x] **2.3** Update `next_work()` to call `resolve_slug(ready_only=True)`
- [x] **2.4** Update `next_work()` to check dependencies before claiming
- [x] **2.5** Update `next_work()` to call `update_roadmap_state()` marking `[>]`
- [x] **2.6** Update `next_prepare()` to call `update_roadmap_state()` marking `[.]`

### Group 3: New MCP Tool

- [x] **3.1** Add `teleclaude__set_dependencies()` method to `McpServer` class
- [x] **3.2** Register tool in `_register_tools()` method
- [x] **3.3** Add tool handler in `_handle_tool_call()` method

### Group 4: Tests

- [ ] **4.1** Add unit tests for `update_roadmap_state()`
- [ ] **4.2** Add unit tests for dependency functions
- [ ] **4.3** Add unit tests for modified `resolve_slug()`
- [ ] **4.4** Add unit test verifying bug check is removed
- [ ] **4.5** Add integration test for full workflow

---

## Detailed Implementation

### 1.1: Add `update_roadmap_state()` function

Location: `teleclaude/core/next_machine.py` (after existing helper functions, around line 370)

```python
def update_roadmap_state(cwd: str, slug: str, new_state: str) -> bool:
    """Update checkbox state for slug in roadmap.md.

    Args:
        cwd: Project root directory
        slug: Work item slug to update
        new_state: One of " " (space), ".", ">", "x"

    Returns:
        True if slug found and updated, False if slug not found

    Side effects:
        - Modifies todos/roadmap.md in place
        - Commits the change to git with descriptive message
    """
    roadmap_path = Path(cwd) / "todos" / "roadmap.md"
    if not roadmap_path.exists():
        return False

    content = roadmap_path.read_text(encoding="utf-8")

    # Pattern: - [STATE] slug where STATE is space, ., >, or x
    pattern = re.compile(rf"^(- \[)[ .>x](\] {re.escape(slug)})(\s|$)", re.MULTILINE)
    new_content, count = pattern.subn(rf"\g<1>{new_state}\g<2>\g<3>", content)

    if count == 0:
        return False

    roadmap_path.write_text(new_content, encoding="utf-8")

    # Commit the state change
    try:
        repo = Repo(cwd)
        repo.index.add(["todos/roadmap.md"])
        state_names = {" ": "pending", ".": "ready", ">": "in-progress", "x": "done"}
        msg = f"roadmap({slug}): mark {state_names.get(new_state, new_state)}"
        repo.index.commit(msg)
        logger.info("Updated roadmap state for %s to %s", slug, new_state)
    except InvalidGitRepositoryError:
        logger.warning("Cannot commit roadmap update: %s is not a git repository", cwd)

    return True
```

### 1.2: Add `read_dependencies()` function

Location: `teleclaude/core/next_machine.py` (after `update_roadmap_state`)

```python
def read_dependencies(cwd: str) -> dict[str, list[str]]:
    """Read dependency graph from todos/dependencies.json.

    Returns:
        Dict mapping slug to list of slugs it depends on.
        Empty dict if file doesn't exist.
    """
    deps_path = Path(cwd) / "todos" / "dependencies.json"
    if not deps_path.exists():
        return {}

    content = deps_path.read_text(encoding="utf-8")
    return json.loads(content)
```

### 1.3: Add `write_dependencies()` function

Location: `teleclaude/core/next_machine.py` (after `read_dependencies`)

```python
def write_dependencies(cwd: str, deps: dict[str, list[str]]) -> None:
    """Write dependency graph to todos/dependencies.json and commit.

    Args:
        cwd: Project root directory
        deps: Dependency graph to write
    """
    deps_path = Path(cwd) / "todos" / "dependencies.json"

    # Remove empty lists to keep file clean
    deps = {k: v for k, v in deps.items() if v}

    if not deps:
        # If no dependencies, remove file if it exists
        if deps_path.exists():
            deps_path.unlink()
            try:
                repo = Repo(cwd)
                repo.index.remove(["todos/dependencies.json"])
                repo.index.commit("deps: remove empty dependencies.json")
            except InvalidGitRepositoryError:
                pass
        return

    deps_path.write_text(json.dumps(deps, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    try:
        repo = Repo(cwd)
        repo.index.add(["todos/dependencies.json"])
        repo.index.commit("deps: update dependencies.json")
        logger.info("Updated dependencies.json")
    except InvalidGitRepositoryError:
        logger.warning("Cannot commit dependencies update: %s is not a git repository", cwd)
```

### 1.4: Add `check_dependencies_satisfied()` function

Location: `teleclaude/core/next_machine.py` (after `write_dependencies`)

```python
def check_dependencies_satisfied(cwd: str, slug: str, deps: dict[str, list[str]]) -> bool:
    """Check if all dependencies for a slug are satisfied.

    A dependency is satisfied if:
    - It is marked [x] in roadmap.md, OR
    - It is not present in roadmap.md (assumed completed/archived), OR
    - It exists in done/*-{dep}/ directory

    Args:
        cwd: Project root directory
        slug: Work item to check
        deps: Dependency graph

    Returns:
        True if all dependencies are satisfied (or no dependencies)
    """
    item_deps = deps.get(slug, [])
    if not item_deps:
        return True

    # Get all slugs currently in roadmap with their states
    roadmap_path = Path(cwd) / "todos" / "roadmap.md"
    if not roadmap_path.exists():
        return True  # No roadmap = no blocking

    content = roadmap_path.read_text(encoding="utf-8")
    pattern = re.compile(r"^- \[([x.> ])\] ([a-z0-9-]+)", re.MULTILINE)

    roadmap_items: dict[str, str] = {}
    for match in pattern.finditer(content):
        state, item_slug = match.groups()
        roadmap_items[item_slug] = state

    for dep in item_deps:
        if dep not in roadmap_items:
            # Not in roadmap - check if archived
            if get_archive_path(cwd, dep) is None:
                # Not archived either - dependency doesn't exist
                # This shouldn't happen if validation worked, but treat as unsatisfied
                return False
            # Archived = satisfied
            continue

        dep_state = roadmap_items[dep]
        if dep_state != "x":
            # Dependency exists but not completed
            return False

    return True
```

### 1.5: Add `detect_circular_dependency()` function

Location: `teleclaude/core/next_machine.py` (after `check_dependencies_satisfied`)

```python
def detect_circular_dependency(deps: dict[str, list[str]], slug: str, new_deps: list[str]) -> list[str] | None:
    """Detect if adding new_deps to slug would create a cycle.

    Args:
        deps: Current dependency graph
        slug: Item we're updating
        new_deps: New dependencies for slug

    Returns:
        List representing the cycle path if cycle detected, None otherwise
    """
    # Build graph with proposed change
    graph = {k: set(v) for k, v in deps.items()}
    graph[slug] = set(new_deps)

    # DFS to detect cycle
    visited: set[str] = set()
    path: list[str] = []

    def dfs(node: str) -> list[str] | None:
        if node in path:
            # Found cycle - return path from cycle start
            cycle_start = path.index(node)
            return path[cycle_start:] + [node]

        if node in visited:
            return None

        visited.add(node)
        path.append(node)

        for dep in graph.get(node, set()):
            result = dfs(dep)
            if result:
                return result

        path.pop()
        return None

    # Check from the slug we're modifying
    for dep in new_deps:
        path = [slug]
        visited = {slug}
        result = dfs(dep)
        if result:
            return [slug] + result

    return None
```

### 2.1: Remove bug check from `next_work()`

Location: `teleclaude/core/next_machine.py`, lines 641-653

DELETE this entire block:

```python
    # 0. Bug check (only when no explicit slug - bugs are priority)
    if not slug and has_pending_bugs(cwd):
        agent, mode = await get_available_agent(db, "bugs", WORK_FALLBACK)
        return format_tool_call(
            command="next-bugs",
            args="",
            project=cwd,
            agent=agent,
            thinking_mode=mode,
            subfolder="",
            note="Fix bugs in todos/bugs.md before proceeding with roadmap work.",
            next_call="teleclaude__next_work",
        )
```

Also remove `has_pending_bugs` from the function if it becomes unused (check other usages first). The function itself can remain in the file for potential standalone use.

### 2.2: Modify `resolve_slug()` to accept `ready_only` parameter

Location: `teleclaude/core/next_machine.py`, function `resolve_slug()` starting at line 287

Change signature and add logic:

```python
def resolve_slug(cwd: str, slug: str | None, ready_only: bool = False) -> tuple[str | None, bool, str]:
    """Resolve slug from argument or roadmap.

    Roadmap format expected:
        - [ ] my-slug   (pending - not prepared)
        - [.] my-slug   (ready - prepared, available for work)
        - [>] my-slug   (in progress - claimed by worker)

    Args:
        cwd: Current working directory (project root)
        slug: Optional explicit slug
        ready_only: If True, only match [.] items (for next_work)

    Returns:
        Tuple of (slug, is_ready_or_in_progress, description).
        If slug provided, returns (slug, True, "").
        If found in roadmap, returns (slug, True if [.] or [>], False if [ ], description).
        If nothing found, returns (None, False, "").
    """
    if slug:
        return slug, True, ""

    roadmap_path = Path(cwd) / "todos" / "roadmap.md"
    if not roadmap_path.exists():
        return None, False, ""

    content = roadmap_path.read_text(encoding="utf-8")

    if ready_only:
        # Only match [.] items for next_work
        pattern = re.compile(r"^-\s+\[\.]\s+(\S+)", re.MULTILINE)
    else:
        # Match [ ], [.], or [>] for next_prepare
        pattern = re.compile(r"^-\s+\[([ .>])\]\s+(\S+)", re.MULTILINE)

    for match in pattern.finditer(content):
        if ready_only:
            found_slug = match.group(1)
            # For ready_only, we know it's [.] so it's "ready"
            is_ready = True
        else:
            status = match.group(1)
            found_slug = match.group(2)
            is_ready = status in (".", ">")

        # Extract description (same logic as before)
        start_pos = match.end()
        next_item = re.search(r"^-\s+\[", content[start_pos:], re.MULTILINE)
        next_section = re.search(r"^##", content[start_pos:], re.MULTILINE)

        end_pos = len(content)
        if next_item:
            end_pos = min(end_pos, start_pos + next_item.start())
        if next_section:
            end_pos = min(end_pos, start_pos + next_section.start())

        description = content[start_pos:end_pos].strip()
        return found_slug, is_ready, description

    return None, False, ""
```

### 2.3-2.5: Update `next_work()` function

Location: `teleclaude/core/next_machine.py`, function `next_work()` starting at line 628

After removing bug check (2.1), modify the function:

```python
async def next_work(db: Db, slug: str | None, cwd: str) -> str:
    """Phase B state machine for deterministic builder work.

    Executes the build/review/fix/finalize cycle on prepared work items.
    Only considers [.] items (ready) with satisfied dependencies.

    Args:
        db: Database instance
        slug: Optional explicit slug (resolved from roadmap if not provided)
        cwd: Current working directory (project root)

    Returns:
        Plain text instructions for the orchestrator to execute
    """
    # 1. Resolve slug - only ready items when no explicit slug
    deps = read_dependencies(cwd)

    if slug:
        # Explicit slug provided - use it directly
        resolved_slug = slug
        is_ready = True
        description = ""
    else:
        # Find first [.] item with satisfied dependencies
        resolved_slug = None
        roadmap_path = Path(cwd) / "todos" / "roadmap.md"
        if roadmap_path.exists():
            content = roadmap_path.read_text(encoding="utf-8")
            pattern = re.compile(r"^-\s+\[\.]\s+([a-z0-9-]+)", re.MULTILINE)

            for match in pattern.finditer(content):
                candidate_slug = match.group(1)
                if check_dependencies_satisfied(cwd, candidate_slug, deps):
                    resolved_slug = candidate_slug
                    break

        if not resolved_slug:
            # Check if there are [.] items but with unsatisfied deps
            if roadmap_path.exists():
                content = roadmap_path.read_text(encoding="utf-8")
                if "[.]" in content:
                    return format_error(
                        "DEPS_UNSATISFIED",
                        "Ready items exist but all have unsatisfied dependencies.",
                        next_call="Complete dependency items first, or check todos/dependencies.json.",
                    )
            return format_error(
                "NO_READY_ITEMS",
                "No [.] (ready) items found in roadmap.",
                next_call="Call teleclaude__next_prepare() to prepare items first.",
            )

        is_ready = True
        description = ""

    # 2. Check if already finalized
    archive_path = get_archive_path(cwd, resolved_slug)
    if archive_path:
        return format_complete(resolved_slug, archive_path)

    # 3. Validate preconditions
    has_requirements = check_file_exists(cwd, f"todos/{resolved_slug}/requirements.md")
    has_impl_plan = check_file_exists(cwd, f"todos/{resolved_slug}/implementation-plan.md")
    if not (has_requirements and has_impl_plan):
        return format_error(
            "NOT_PREPARED",
            f"todos/{resolved_slug} is missing requirements or implementation plan.",
            next_call=f'Call teleclaude__next_prepare("{resolved_slug}") to complete preparation.',
        )

    # 4. Ensure worktree exists
    worktree_created = ensure_worktree(cwd, resolved_slug)
    if worktree_created:
        logger.info("Created new worktree for %s", resolved_slug)

    worktree_cwd = str(Path(cwd) / "trees" / resolved_slug)

    # 5. Check uncommitted changes
    if has_uncommitted_changes(cwd, resolved_slug):
        return format_uncommitted_changes(resolved_slug)

    # 6. Mark as in-progress BEFORE dispatching (claim the item)
    # Only mark if currently [.] (not already [>])
    roadmap_path = Path(cwd) / "todos" / "roadmap.md"
    if roadmap_path.exists():
        content = roadmap_path.read_text(encoding="utf-8")
        if f"[.] {resolved_slug}" in content:
            update_roadmap_state(cwd, resolved_slug, ">")

    # 7. Check build status (from state.json in worktree)
    if not is_build_complete(worktree_cwd, resolved_slug):
        agent, mode = await get_available_agent(db, "build", WORK_FALLBACK)
        return format_tool_call(
            command="next-build",
            args=resolved_slug,
            project=cwd,
            agent=agent,
            thinking_mode=mode,
            subfolder=f"trees/{resolved_slug}",
            next_call="teleclaude__next_work",
        )

    # 8. Check review status
    if not is_review_approved(worktree_cwd, resolved_slug):
        if is_review_changes_requested(worktree_cwd, resolved_slug):
            agent, mode = await get_available_agent(db, "fix", WORK_FALLBACK)
            return format_tool_call(
                command="next-fix-review",
                args=resolved_slug,
                project=cwd,
                agent=agent,
                thinking_mode=mode,
                subfolder=f"trees/{resolved_slug}",
                next_call="teleclaude__next_work",
            )
        agent, mode = await get_available_agent(db, "review", WORK_FALLBACK)
        return format_tool_call(
            command="next-review",
            args=resolved_slug,
            project=cwd,
            agent=agent,
            thinking_mode=mode,
            subfolder=f"trees/{resolved_slug}",
            next_call="teleclaude__next_work",
        )

    # 9. Review approved - dispatch finalize
    agent, mode = await get_available_agent(db, "finalize", WORK_FALLBACK)
    return format_tool_call(
        command="next-finalize",
        args=resolved_slug,
        project=cwd,
        agent=agent,
        thinking_mode=mode,
        subfolder="",
        next_call="teleclaude__next_work",
    )
```

### 2.6: Update `next_prepare()` to mark `[.]`

Location: `teleclaude/core/next_machine.py`, function `next_prepare()`, around line 624 (the "Both exist - prepared" case)

Change:

```python
    # 4. Both exist - prepared
    return format_prepared(resolved_slug)
```

To:

```python
    # 4. Both exist - mark as ready and return prepared
    update_roadmap_state(cwd, resolved_slug, ".")
    return format_prepared(resolved_slug)
```

### 3.1-3.3: Add `teleclaude__set_dependencies()` tool

Location: `teleclaude/mcp_server.py`

**3.1: Add method to McpServer class** (after `teleclaude__mark_phase`, around line 2460):

```python
async def teleclaude__set_dependencies(
    self,
    slug: str,
    after: list[str],
    cwd: str | None = None,
) -> str:
    """Set dependencies for a work item.

    Replaces all dependencies for the slug. Use after=[] to clear.

    Args:
        slug: Work item slug
        after: List of slugs that must complete before this one
        cwd: Working directory (auto-injected)

    Returns:
        Success message or error
    """
    if not cwd:
        return "ERROR: NO_CWD\nWorking directory not provided."

    # Import here to avoid circular import
    from teleclaude.core.next_machine import (
        detect_circular_dependency,
        read_dependencies,
        write_dependencies,
    )

    # Validate slug format
    slug_pattern = re.compile(r"^[a-z0-9-]+$")
    if not slug_pattern.match(slug):
        return f"ERROR: INVALID_SLUG\nSlug '{slug}' must be lowercase alphanumeric with hyphens only."

    for dep in after:
        if not slug_pattern.match(dep):
            return f"ERROR: INVALID_DEP\nDependency '{dep}' must be lowercase alphanumeric with hyphens only."

    # Check self-reference
    if slug in after:
        return f"ERROR: SELF_REFERENCE\nSlug '{slug}' cannot depend on itself."

    # Read roadmap to validate slugs exist
    roadmap_path = Path(cwd) / "todos" / "roadmap.md"
    if not roadmap_path.exists():
        return "ERROR: NO_ROADMAP\ntodos/roadmap.md not found."

    content = roadmap_path.read_text(encoding="utf-8")

    # Check slug exists in roadmap
    if slug not in content:
        return f"ERROR: SLUG_NOT_FOUND\nSlug '{slug}' not found in roadmap.md."

    # Check all dependencies exist in roadmap
    for dep in after:
        if dep not in content:
            return f"ERROR: DEP_NOT_FOUND\nDependency '{dep}' not found in roadmap.md."

    # Read current dependencies
    deps = read_dependencies(cwd)

    # Check for circular dependency
    cycle = detect_circular_dependency(deps, slug, after)
    if cycle:
        cycle_str = " -> ".join(cycle)
        return f"ERROR: CIRCULAR_DEP\nCircular dependency detected: {cycle_str}"

    # Update and write
    if after:
        deps[slug] = after
    elif slug in deps:
        del deps[slug]

    write_dependencies(cwd, deps)

    if after:
        return f"OK: Dependencies set for '{slug}': {', '.join(after)}"
    return f"OK: Dependencies cleared for '{slug}'"
```

**3.2: Register tool** in `_register_tools()` method (find the tool registration section, around line 720-740):

```python
Tool(
    name="teleclaude__set_dependencies",
    description="Set dependencies for a work item. Use after=[] to clear.",
    inputSchema={
        "type": "object",
        "properties": {
            "slug": {
                "type": "string",
                "description": "Work item slug",
            },
            "after": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of slugs that must complete before this item can be worked on",
            },
        },
        "required": ["slug", "after"],
    },
),
```

**3.3: Add handler** in `_handle_tool_call()` method (find the elif chain for tool handlers):

```python
elif name == "teleclaude__set_dependencies":
    slug = str(arguments.get("slug", ""))
    after = arguments.get("after", [])
    if not isinstance(after, list):
        after = []
    after = [str(a) for a in after]
    result_text = await self.teleclaude__set_dependencies(slug, after, cwd)
```

### 4.1-4.5: Tests

Location: `tests/unit/test_next_machine.py` (create if doesn't exist)

See requirements.md for test cases. Create tests covering:
- `update_roadmap_state()` transitions
- `read_dependencies()` and `write_dependencies()`
- `check_dependencies_satisfied()` scenarios
- `detect_circular_dependency()` with cycles and without
- `resolve_slug()` with `ready_only=True`
- Full `next_work()` flow without bug check

---

## Execution Order

1. **Group 1 first** - Infrastructure functions have no dependencies
2. **Group 2 next** - Modify existing functions using new infrastructure
3. **Group 3 then** - New tool depends on infrastructure
4. **Group 4 last** - Tests validate everything

---

## Post-Implementation

1. Update `todos/roadmap.md` status legend to include `[.]`:
   ```
   > **Status Legend**: `[ ]` = Pending | `[.]` = Ready | `[>]` = In Progress
   ```

2. Run `make lint` and `make test` to verify

3. Test manually:
   - Call `teleclaude__next_prepare()` on a `[ ]` item → should mark `[.]`
   - Call `teleclaude__next_work()` → should claim first `[.]` item and mark `[>]`
   - Call `teleclaude__set_dependencies()` → should update dependencies.json
