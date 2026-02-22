# Requirements: state-yaml-migration

## Goal

Migrate all todo `state.json` files to `state.yaml` format, making the todo system's serialization consistent with `roadmap.yaml` and `icebox.yaml`. YAML is more readable for humans, supports inline comments, and aligns the entire todo system on a single serialization format.

## Scope

### In scope:

- Rename all code references from `state.json` to `state.yaml`
- Update the central read/write functions in `teleclaude/core/next_machine/core.py` (`get_state_path`, `read_phase_state`, `write_phase_state`) to use YAML
- Update the scaffold in `teleclaude/todo_scaffold.py` to generate `state.yaml`
- Update validation in `teleclaude/resource_validation.py` to expect `state.yaml`
- Update `teleclaude/core/roadmap.py` to read `state.yaml` instead of `state.json`
- Update the worktree sync file lists in `sync_slug_todo_from_worktree_to_main` and `sync_slug_todo_from_main_to_worktree`
- Update `sweep_completed_groups` which reads `state.json` directly
- Update `teleclaude/core/todo_watcher.py` docstring reference
- Migrate all 34 existing `todos/*/state.json` files to `state.yaml`
- Add backward-compat fallback: reader checks `state.yaml` first, falls back to `state.json`
- Update all unit/integration tests that reference `state.json`
- Update `roadmap.yaml` header comment that says "Per-item state in {slug}/state.json"
- Update `save_roadmap` header in `core.py` to reference `state.yaml`
- Update agent command docs (next-build, next-review, etc.) that mention `state.json`
- Update doc snippets that reference `state.json`

### Out of scope:

- `.state.json` in `teleclaude/mcp_server.py` (MCP tool signature state — different purpose, not a todo state file)
- `cron_state.json` in `teleclaude/cron/state.py` (cron state — different system)
- `tui_state.json` in `teleclaude/paths.py` (TUI persistence — different system)
- Schema changes to the Pydantic models (`TodoState`, `DorState`, `BreakdownState`)
- Any behavioral changes — pure format migration

## Success Criteria

- [ ] All todo state files are stored as `state.yaml`
- [ ] `state.json` fallback works: reader loads `state.json` when `state.yaml` is missing
- [ ] No `state.json` files remain in `todos/*/` after migration script runs
- [ ] `telec todo validate` passes for all active todos
- [ ] `make test` passes with no regressions
- [ ] `make lint` passes
- [ ] New scaffolded todos create `state.yaml` (not `state.json`)
- [ ] YAML output is human-readable (indented, no flow style, keys in natural order)

## Constraints

- Pydantic models remain unchanged — only serialization format changes
- Backward-compat fallback must exist during transition (reader falls back to `state.json`)
- Must not break in-progress todos that have `state.json` but no `state.yaml` yet
- No schema version bump needed (format change, not schema change)
- YAML serialization must round-trip cleanly with the Pydantic models

## Risks

- Agent command docs and doc snippets may have scattered `state.json` references that are easy to miss — mitigate with grep sweep
- Multi-worktree sync: both `state.json` and `state.yaml` references appear in sync file lists — must update both paths consistently
