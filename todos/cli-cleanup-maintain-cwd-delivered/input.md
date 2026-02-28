# Input: cli-cleanup-maintain-cwd-delivered

Three CLI hygiene items from a single conversation:

## 1. Remove dead `telec todo maintain` command

The entire maintain pipeline is a stub that returns "MAINTENANCE_EMPTY". It has been dead for months. Remove it completely — the command, API route, clearance, tool access entry, skill mapping, and the state machine file.

Files to touch:

- `teleclaude/core/next_machine/maintain.py` — delete
- `teleclaude/core/next_machine/__init__.py` — remove `next_maintain` import
- `teleclaude/api/todo_routes.py` — remove `/maintain` endpoint + import
- `teleclaude/api/auth.py` — remove `CLEARANCE_TODOS_MAINTAIN`
- `teleclaude/cli/tool_commands.py` — remove `handle_todo_maintain`
- `teleclaude/cli/telec.py` — remove from CLI_SURFACE, import, and dispatch
- `teleclaude/core/tool_access.py` — remove from `UNAUTHORIZED_EXCLUDED_TOOLS`
- `teleclaude/core/tool_activity.py` — remove `next_maintain` mapping
- `scripts/diagrams/extract_commands.py` — remove `next-maintain` entry

## 2. Remove `--cwd` and `--project-root` from the entire CLI surface

These flags are an escape hatch that became a liability. Agents always run from their project directory. Humans always `cd` first. There is no use case for "operate on a different project than the one I'm in." The flag metastasized — it went from optional to required on multiple commands.

**Decision:** Strip `--cwd` and `--project-root` from all CLI arg parsing and CLI_SURFACE definitions. Every CLI handler uses `os.getcwd()` unconditionally. The underlying Python functions keep their `cwd` parameter — API routes and internal callers still pass it explicitly.

Files to touch:

- `teleclaude/cli/telec.py` — remove `_PROJECT_ROOT`, `_PROJECT_ROOT_LONG` flag definitions; remove all `--project-root` parsing from every handler (~26 locations); remove from CLI_SURFACE flags
- `teleclaude/cli/tool_commands.py` — remove all `--cwd` parsing from `handle_todo_prepare`, `handle_todo_mark_phase`, `handle_todo_set_deps`; always use `os.getcwd()`

## 3. Add `--include-delivered` / `--delivered-only` flags to `telec roadmap list`

Mirror the existing `--include-icebox` / `--icebox-only` pattern:

- `--include-delivered` includes delivered items alongside active roadmap
- `--delivered-only` shows only delivered items

Data source: `todos/delivered.yaml` (already exists, loaded by `load_delivered_slugs` in core).

Files to touch:

- `teleclaude/cli/telec.py` — add flags to CLI_SURFACE, parse in `_handle_roadmap_show`
- `teleclaude/core/roadmap.py` — add `include_delivered` / `delivered_only` params to `assemble_roadmap`, load delivered entries
- `teleclaude/core/next_machine/core.py` — may need a `load_delivered` function that returns full records (not just slugs)
