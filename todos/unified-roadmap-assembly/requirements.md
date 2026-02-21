# Requirements: unified-roadmap-assembly

## Goal

Consolidate the three separate roadmap/todo data paths into a single core function that produces rich, structured `TodoInfo` output. Make `telec roadmap` the canonical local producer that both the CLI and API consume.

## Problem

Three code paths read the same `roadmap.yaml` + `todos/{slug}/state.json` data at different fidelity levels:

1. **`telec roadmap` CLI** (`telec.py:_handle_roadmap_show`) — calls `load_roadmap()` directly, reads `state.json` manually, only extracts `phase`. Discards DOR, build/review status, findings, deferrals, files.
2. **`command_handlers.list_todos()`** — the rich path. Reads roadmap, cross-references state.json, computes DOR scores, build/review status, findings, deferrals, file lists, groups, deps, breakdown trees. Returns `TodoInfo`.
3. **API `/todos` endpoint** — calls `command_handlers.list_todos()` for local data, cache for remote. TUI consumes this.

The CLI bypasses the rich pipeline. There is no structured output format for wire transport.

## In scope

- Extract the rich assembly logic from `command_handlers.list_todos()` into a standalone core function
- Make `telec roadmap` use that core function for terminal rendering
- Add `--json` flag to `telec roadmap` for structured output (wire format)
- Add `-i` / `--include-icebox` flag (roadmap + icebox items)
- Add `-o` / `--icebox-only` flag (icebox items only)
- Make `command_handlers.list_todos()` a thin wrapper around the core function
- Update CLI_SURFACE with the new flags

## Out of scope

- Remote wire transport protocol changes (depends on `--json` existing)
- TUI rendering changes (already works, consumes same `TodoInfo` shape)
- Changes to `TodoInfo`, `TodoDTO`, or `TodoItem` data models
- Icebox management commands (freeze/thaw already exist)

## Success Criteria

- [ ] `telec roadmap` renders rich output: slug, group, DOR score, build/review status, findings, deps
- [ ] `telec roadmap --json` outputs structured JSON matching `TodoInfo` fields
- [ ] `telec roadmap -o` shows only icebox items
- [ ] `telec roadmap -i` shows roadmap + icebox items together
- [ ] `command_handlers.list_todos()` delegates to the core function (no duplicated logic)
- [ ] TUI preparation view continues to work unchanged
- [ ] `telec roadmap` CLI check hook passes (`-h` exits 0)
- [ ] `make lint` and `make test` pass

## Constraints

- `TodoInfo` dataclass shape must not change (it's the shared contract)
- The core function must be synchronous (CLI calls it directly, no async)
- Icebox items use the same `RoadmapEntry` schema as roadmap items
- The orphan-directory scan (dirs in `todos/` not in roadmap) must be preserved

## Risks

- `command_handlers.list_todos()` is async; the core function must be sync. The async wrapper must handle this cleanly.
- The breakdown/container-child injection logic at the end of `list_todos()` is complex — must be extracted intact.
