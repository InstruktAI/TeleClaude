# Review Findings: cli-knowledge-commands

## Re-review (Round 2)

Previous review (REQUEST CHANGES) raised 2 Important findings. Both have been fixed.
This is a re-review verifying the fixes and checking for any new issues.

## Paradigm-Fit Assessment

The implementation follows established codebase patterns:

- **Data flow**: Uses `TelecAPIClient` for daemon-dependent memory operations and proper package imports for history operations. No inline hacks.
- **Component reuse**: Follows `CommandDef` registration pattern, `_handle_*` dispatch pattern, and `asyncio.run()` + `TelecAPIClient` connection lifecycle pattern established by adjacent handlers (e.g., `_revive_session_via_api`).
- **Pattern consistency**: Argument parsing, help output, error messages, and `SystemExit(1)` on failure all match the idioms used by `_handle_docs`, `_handle_sessions`, and `_handle_config`.

No paradigm violations found.

## Requirements Tracing

All 14 success criteria from `requirements.md` are addressed:

- `telec history search` and `telec history show` — implemented and wired
- `telec memories search|save|delete|timeline` — implemented and wired
- `telec -h` shows both new commands — verified via `_usage()` test
- Tool spec files deleted (3 files) — confirmed in diff
- `docs/global/baseline.md` references removed — confirmed in diff
- `telec-cli` spec updated with new subcommand definitions — confirmed in diff
- See Also references updated across docs — confirmed in diff

## Principle Violation Hunt

- **Fallback/Silent Degradation**: No unjustified fallbacks. The `marker = ""` fallback on invalid ID in timeline renderer is justified — it's a display decoration for the anchor marker, not data correctness. The fallback is guarded with `try/except (ValueError, TypeError)`.
- **Fail Fast**: Input validation at all boundaries — missing args, invalid types, invalid IDs all trigger `SystemExit(1)` with clear messages.
- **DIP**: No core-importing-adapter violations. History functions properly extracted into `teleclaude.history.search`.
- **Coupling**: No deep chains or god object patterns.
- **SRP**: Each handler has a single responsibility.
- **YAGNI/KISS**: No premature abstractions. Straightforward implementation.

## Critical

None.

## Important

None. Both previous Important findings have been fixed (see Fixes Applied below).

## Suggestions

### 1. `sys.exit(1)` in library functions `parse_agents` and `show_transcript`

**File:** `teleclaude/history/search.py:200, 271`

These functions were extracted from `scripts/history.py` into a library module. They still call `sys.exit(1)` directly instead of raising exceptions. Now that they're public library APIs imported by `telec.py`, this couples them to CLI context and makes them non-composable. Pre-existing behavior carried forward — not blocking, but worth a follow-up to raise `ValueError` / `LookupError` and let CLI handlers convert to `SystemExit`.

### 2. Memory handlers catch only `APIError`, not `OSError` from `connect()`

**File:** `teleclaude/cli/telec.py:3618, 3701, 3752, 3835`

If the daemon socket is missing or has wrong permissions, `api.connect()` raises `OSError` which is not caught by `except APIError`. The user sees a raw traceback instead of a clean "daemon not running" message. However, **this matches the existing pattern** used by all other daemon-dependent handlers in `telec.py` (e.g., `_revive_session`). Fixing this should be a cross-cutting improvement, not scoped to this delivery.

### 3. Thread pool exception propagation in `scan_agent_history`

**File:** `teleclaude/history/search.py:165-170`

`future.result()` re-raises any exception from `_scan_one`. One corrupt transcript file crashes the entire search. Pre-existing behavior from `scripts/history.py`, carried forward as-is per the delivery scope ("surface consolidation, not new behavior"). Worth a follow-up to wrap in `try/except`.

### 4. Test mock targets patch source module, not usage site

**File:** `tests/unit/test_telec_knowledge_commands.py:50-51, 69-70, 97-98`

Tests patch `"teleclaude.history.search.parse_agents"` rather than where it's used. This works because `_handle_history_search` uses a deferred local import, so the name is re-bound from the source module each call. If the import were ever moved to module-level, the patches would silently stop intercepting. Not a correctness issue today; fragility risk for future refactors.

## Demo Review

All 5 executable blocks verified against the implementation:

1. `telec history search` — uses actual command and flags that exist.
2. `telec history show` — correctly extracts session ID from search results, then calls `show`. Fixed from previous round.
3. Memory save + search + delete round-trip — exercises the full CRUD lifecycle.
4. Help output — verifies both subcommands appear.
5. Tool spec retirement — confirms deleted files and cleaned baseline references.

No fabricated output. No commands or flags that don't exist.

## Why No Critical or Important Issues

1. **Paradigm-fit verified**: All handlers follow the `_handle_*` dispatch pattern, `CommandDef` registration, and `TelecAPIClient` connection lifecycle established by adjacent code.
2. **Requirements verified**: All 14 success criteria traced to implementation.
3. **No copy-paste duplication**: History functions extracted into shared module; no code duplicated between `scripts/history.py` and `teleclaude/history/search.py`.
4. **Error handling at boundaries**: All user input is validated (missing args, invalid types, invalid IDs) with clear error messages and `SystemExit(1)`.
5. **Principle violation hunt**: No unjustified fallback paths. Timeline marker fallback is justified (display decoration). All suggestions are pre-existing behaviors carried forward from the original code, consistent with the delivery scope of "surface consolidation, not new behavior."

## Fixes Applied (from Round 1)

### Finding 1 — `int(obs_id)` crash in timeline renderer
**Fix:** Wrapped `int(obs_id)` in `try/except (ValueError, TypeError)`; sets `marker = ""` on failure.
**Commit:** `24d56906`
**Verified:** Fix confirmed at `teleclaude/cli/telec.py:3848-3851`.

### Finding 2 — Demo block 2 mislabeled
**Fix:** Replaced the mislabeled search command with an actual `telec history show` invocation that extracts a session ID from search results.
**Commit:** `e5beac2b`
**Verified:** Fix confirmed at `demos/cli-knowledge-commands/demo.md:10-13`.

## Verdict: APPROVE
