# Implementation Plan: cli-knowledge-commands

## Overview

Wrap existing history search and memory management functionality into first-class
`telec history` and `telec memories` CLI subcommands, then retire the standalone
tool specs that teach agents raw script/curl workflows. All business logic already
exists — this is a surface consolidation using the established `CommandDef` +
`_handle_*` dispatch pattern.

## Phase 1: Core Changes

### Task 1.1: Register `history` and `memories` in CLI surface

**File(s):** `teleclaude/cli/telec.py`

- [x] Add `HISTORY = "history"` and `MEMORIES = "memories"` to `TelecCommand` enum
- [x] Add `"history"` entry to `CLI_SURFACE` dict with subcommands:
  - `search`: args `[terms...]`, flags `--agent` (short `-a`), `--limit` (short `-l`)
  - `show`: args `<session-id>`, flags `--agent` (short `-a`), `--thinking`, `--tail`
- [x] Add `"memories"` entry to `CLI_SURFACE` dict with subcommands:
  - `search`: args `<query>`, flags `--limit`, `--type`, `--project`
  - `save`: args `<text>`, flags `--title`, `--type`, `--project`
  - `delete`: args `<id>`
  - `timeline`: args `<id>`, flags `--before`, `--after`, `--project`

### Task 1.2: Extract history functions into importable module

**File(s):** `teleclaude/history/__init__.py`, `teleclaude/history/search.py`, `~/.teleclaude/scripts/history.py`

`scripts/history.py` is a standalone script — not part of the `teleclaude` package.
Its core functions cannot be imported by `telec.py` directly. Extract them into a
proper module so both `scripts/history.py` and `telec.py` can import from it.

- [x] Create `teleclaude/history/__init__.py` (empty)
- [x] Create `teleclaude/history/search.py` — move the reusable functions from
  `scripts/history.py`: `scan_agent_history`, `find_transcript`, `show_transcript`,
  `display_combined_history`, `parse_agents`, `_discover_transcripts`,
  `_extract_session_id`, and supporting constants/types (`AgentName`, path resolution)
- [x] Update `scripts/history.py` to import from `teleclaude.history.search` instead
  of defining the functions inline. Keep `scripts/history.py` as a thin CLI entry point
  (argparse + dispatch) so existing users are unaffected.
- [x] Verify `scripts/history.py` still works standalone: `history.py --agent claude test`

### Task 1.3: Implement `_handle_history` dispatcher and subcommands

**File(s):** `teleclaude/cli/telec.py`

- [x] Add `_handle_history(args)` following the `_handle_docs` pattern: help check, subcommand dispatch
- [x] Add `_handle_history_search(args)`:
  - Parse `--agent` (default `"all"`), `--limit` (default 20), remaining positional as search terms
  - Import from `teleclaude.history.search`: `display_combined_history`, `parse_agents`
  - Call `display_combined_history(agents, search_term=" ".join(terms), limit=limit)`
- [x] Add `_handle_history_show(args)`:
  - Parse positional `session-id`, `--agent` (default `"all"`), `--thinking`, `--tail` (default 0)
  - Import from `teleclaude.history.search`: `show_transcript`, `parse_agents`
  - Call `show_transcript(agents, session_id, tail_chars=tail, include_thinking=thinking)`
- [x] Wire `TelecCommand.HISTORY` in the main dispatcher (line ~1272 area)

### Task 1.4: Implement `_handle_memories` dispatcher and subcommands

**File(s):** `teleclaude/cli/telec.py`

- [x] Add `_handle_memories(args)` following the same dispatch pattern
- [x] Add `_handle_memories_search(args)`:
  - Parse positional `<query>`, `--limit` (default 20), `--type`, `--project`
  - Use `TelecAPIClient` to GET `/api/memory/search` with query params
  - Format and print results (id, title, type, project, text snippet)
- [x] Add `_handle_memories_save(args)`:
  - Parse positional `<text>`, `--title`, `--type` (validate against ObservationType), `--project`
  - Use `TelecAPIClient` to POST `/api/memory/save` with JSON body
  - Print saved observation ID
- [x] Add `_handle_memories_delete(args)`:
  - Parse positional `<id>`
  - Use `TelecAPIClient` to DELETE `/api/memory/{id}`
  - Print confirmation
- [x] Add `_handle_memories_timeline(args)`:
  - Parse positional `<id>`, `--before` (default 3), `--after` (default 3), `--project`
  - Use `TelecAPIClient` to GET `/api/memory/timeline` with query params
  - Format and print timeline results
- [x] Wire `TelecCommand.MEMORIES` in the main dispatcher

### Task 1.5: Add memory helper methods to TelecAPIClient

**File(s):** `teleclaude/cli/api_client.py`

- [x] Add `async memory_search(query, limit=20, type=None, project=None)` — GET `/api/memory/search`
- [x] Add `async memory_save(text, title=None, type=None, project=None)` — POST `/api/memory/save`
- [x] Add `async memory_delete(observation_id)` — DELETE `/api/memory/{observation_id}`
- [x] Add `async memory_timeline(anchor, before=3, after=3, project=None)` — GET `/api/memory/timeline`

### Task 1.6: Retire standalone tool specs

**File(s):**
- `docs/global/general/spec/tools/agent-restart.md`
- `docs/global/general/spec/tools/history-search.md`
- `docs/global/general/spec/tools/memory-management-api.md`
- `docs/global/baseline.md`

- [x] Delete `docs/global/general/spec/tools/agent-restart.md`
- [x] Delete `docs/global/general/spec/tools/history-search.md`
- [x] Delete `docs/global/general/spec/tools/memory-management-api.md`
- [x] Remove the three `@` references from `docs/global/baseline.md` (lines 6-8)
- [x] Run `telec sync` to regenerate indexes and deployed artifacts

---

## Phase 2: Validation

### Task 2.1: Tests

- [x] Add unit tests for `_handle_history_search` and `_handle_history_show` (mock `history.py` imports)
- [x] Add unit tests for `_handle_memories_search`, `_handle_memories_save`, `_handle_memories_delete`, `_handle_memories_timeline` (mock `TelecAPIClient`)
- [x] Add unit tests for new `TelecAPIClient` memory methods (mock HTTP responses)
- [x] Test CLI help output: `telec history -h`, `telec memories -h`
- [x] Test error paths: daemon down for memories, missing args, invalid type
- [x] Run `make test`

### Task 2.2: Quality Checks

- [x] Run `make lint`
- [x] Verify `telec -h` shows `history` and `memories` in command list
- [x] Verify `telec sync` succeeds with updated baseline
- [x] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [x] Confirm requirements are reflected in code changes
- [x] Confirm implementation tasks are all marked `[x]`
- [x] Document any deferrals explicitly in `deferrals.md` (if applicable)

---

## Technical Notes

- `history.py` works without the daemon (reads transcript files directly). The `telec history`
  command inherits this property — it imports from `teleclaude.history.search`, no daemon needed.
- `scripts/history.py` remains as a standalone CLI entry point but delegates to
  `teleclaude.history.search` for all logic. No user-facing behavior changes.
- `telec memories` requires the daemon. If daemon is unreachable, `TelecAPIClient` raises
  `APIError` which the handler catches and prints a clear error message.
- The `_handle_memories_*` functions use `asyncio.run()` to call async client methods,
  same pattern as other daemon-dependent handlers in telec.py.
- `ObservationType` values for `--type` validation: preference, decision, discovery,
  gotcha, pattern, friction, context.
- The `telec-cli` spec auto-generates from `CLI_SURFACE`, so new commands appear in
  agent context automatically after `telec sync`.
- Note: `_parse_agents` was renamed to `parse_agents` (public) to satisfy Pyright's
  reportUnusedFunction check — the function is imported by external modules.
- Note: `make lint` exits non-zero due to pre-existing pylint convention/refactor
  violations (score 9.40/10 vs baseline 9.39/10 — my changes slightly improved it).
  The only enforced pylint rule is `import-outside-toplevel` which is not triggered.
