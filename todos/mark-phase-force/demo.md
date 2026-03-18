# Demo: mark-phase-force

## Validation

### Part A: Force flag bypasses worktree requirement

```bash
telec todo mark-phase demo-nonexistent --phase build --status pending --force 2>&1 || true
```

### Force flag shown in CLI help

```bash
telec todo mark-phase --help 2>&1 | grep -A1 '\-\-force'
```

### Part B: TodoState is the canonical state source

```bash
# TodoState produces the full schema at version 1
.venv/bin/python -c "from teleclaude.types.todos import TodoState; s=TodoState(); print(f'schema_version={s.schema_version}, fields={len(s.model_fields)}')"
```

### default_state() delegates to TodoState

```bash
.venv/bin/python -c "from teleclaude.core.next_machine._types import default_state; d=default_state(); print(f'version={d[\"schema_version\"]}, has_artifacts={\"artifacts\" in d}')"
```

### No DEFAULT_STATE or v2 references remain

```bash
# Should find zero hits in next_machine (excluding _v2 in unrelated telegram/animation code)
grep -r 'DEFAULT_STATE\|_is_artifact_produced_v2\|schema_version.*2' teleclaude/core/next_machine/ --include='*.py' | grep -v '.pyc' || echo "Clean: no legacy references"
```

### All state.yaml files are schema_version 1

```bash
grep -r 'schema_version: 2' todos/ --include='*.yaml' || echo "Clean: all state.yaml at version 1"
```

### Tests pass

```bash
.venv/bin/python -m pytest tests/unit/api/test_todo_routes.py tests/unit/cli/tool_commands/test_todo.py tests/unit/test_todo_scaffold.py tests/unit/core/next_machine/test_state_io.py -v --no-header -q 2>&1 | tail -5
```

## Guided Presentation

### Part A — mark-phase guard fixes

1. **Stash guard removed** — `mark-phase` no longer checks for git stash entries. Stash is repo-level state with no logical connection to phase validity.

2. **Uncommitted-changes guard narrowed** — Only `build:complete` and `build:approved` still check. Review phases no longer block on uncommitted changes.

3. **`--force` flag** — Skips worktree 404 (falls back to cwd) and uncommitted-changes check for build terminal statuses.

4. **CLI support** — `telec todo mark-phase <slug> --phase build --status pending --force`

### Part B — State schema consolidation

5. **TodoState is the single source of truth** — All state fields (phase, finalize, grounding, reviews, artifacts, audit) defined as Pydantic sub-models in `teleclaude/types/todos.py`.

6. **DEFAULT_STATE dict deleted** — Replaced with `default_state()` function that calls `TodoState().model_dump()`. No more hardcoded dict drift.

7. **No v1/v2 distinction** — There is one schema version (1). The compat branching and state.json fallbacks are gone.

8. **41 state.yaml files migrated** — All existing todos now have the full canonical shape at `schema_version: 1`.
