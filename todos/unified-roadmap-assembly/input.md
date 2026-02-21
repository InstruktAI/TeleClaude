# Unified Roadmap Assembly

## Problem

Three separate paths read the same roadmap + todo data with different levels of richness:

1. **`telec roadmap` CLI** (`telec.py:_handle_roadmap_show`) — calls `load_roadmap()` directly, does its own dumb `state.json` reading. Only extracts `phase`. Throws away DOR, build/review status, findings, deferrals, files.

2. **`command_handlers.list_todos()`** — the rich path. Reads `roadmap.yaml` + `todos/{slug}/state.json`, computes DOR scores, build/review status, findings count, deferrals, file lists, groups, deps. Produces `TodoInfo` objects.

3. **API `/todos` endpoint** — calls `command_handlers.list_todos()` for local, reads from cache for remote. TUI consumes this.

The CLI bypasses the rich pipeline entirely. The TUI gets full data integrity. There is no `--json` output for wire transport.

## Goal

One core function that everyone calls. `telec roadmap` becomes the canonical local producer. Remote computers run their own `telec roadmap --json` and send structured data over the wire. The API assembles.

```
core function: assemble_roadmap(project_path) → list[TodoInfo]
  ├── telec roadmap        (CLI, calls directly, renders for terminal or --json)
  ├── command_handlers     (thin wrapper, API server calls for local)
  └── remote               (remote telec roadmap --json, sent over wire)
```

## Changes

1. **Extract core function** — move the rich assembly logic from `command_handlers.list_todos()` into a pure function in `core/` (e.g., `core/next_machine/core.py` or a new `core/roadmap.py`). Signature: `assemble_roadmap(project_path: str) -> list[TodoInfo]`. This reads roadmap.yaml, cross-references todos/{slug}/state.json, computes all metadata.

2. **`command_handlers.list_todos()` becomes thin wrapper** — calls `assemble_roadmap()` instead of duplicating the logic.

3. **`telec roadmap` uses the core function** — replace `_handle_roadmap_show()` with a call to `assemble_roadmap()`. Render rich terminal output (groups, DOR, build/review, findings, deps). Add `--json` flag for structured output (wire format).

4. **Icebox flags** — `telec roadmap` gets two new flags:
   - `-i` / `--include-icebox` — show roadmap + icebox items together
   - `-o` / `--icebox-only` — show only icebox items

   Default (no flag) shows roadmap only, which is current behavior. The icebox uses the same `assemble_roadmap()` core function since `icebox.yaml` shares the `RoadmapEntry` schema. This replaces the need for a separate `telec icebox` command.

5. **Verify TUI data integrity** — the TUI's `TodoDTO` → `TodoItem` pipeline should be unaffected since the underlying data shape (`TodoInfo`) doesn't change.

## Key files

- `teleclaude/core/command_handlers.py` — `list_todos()` (lines 491-690+)
- `teleclaude/cli/telec.py` — `_handle_roadmap_show()` (lines 1182-1234)
- `teleclaude/api_models.py` — `TodoDTO`, `TodoInfo`
- `teleclaude/api_server.py` — `/todos` endpoint

## Not in scope

- Remote wire transport changes (that's a separate concern once `--json` exists)
- TUI rendering changes (it already works, just needs the same data source)
