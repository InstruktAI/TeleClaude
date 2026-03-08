# Review Findings: history-search-upgrade

## Review Scope

Reviewed all files in `git diff $(git merge-base HEAD main)..HEAD` against `requirements.md`, `implementation-plan.md`, project policies, and design principles.

## Completeness

All implementation-plan tasks are checked `[x]`. All success criteria in requirements.md have corresponding implementations. Deferrals are resolved (audit trail only).

## Critical

None.

## Important

### 1. CLI help text missing new flags

**Location:** `teleclaude/cli/telec.py:806-818` (search), `teleclaude/cli/telec.py:821-836` (show)

`CLI_SURFACE` definition for `history search` is missing the `--computer` flag. `history show` is missing both `--computer` and `--raw` flags. The flags are correctly wired in the handler functions (`_handle_history_search`, `_handle_history_show`) but absent from the `CommandDef` flag lists. This means `--help` output and the auto-generated AGENTS.md system prompt won't document the new capabilities. Per DoD: "CLI help text updated for new/changed subcommands."

**Fix:** Add `Flag("--computer", desc="Query one or more remote computers via daemon API")` to the search flags, and `Flag("--computer", desc="Fetch from a remote computer")` plus `Flag("--raw", desc="Show raw transcript instead of mirror text")` to the show flags.

### 2. Duplicate transcript discovery logic

**Location:** `teleclaude/history/search.py:65-90` and `teleclaude/mirrors/worker.py:30-52`

`_discover_transcripts()` exists in both modules with near-identical logic. Similarly `_extract_session_id` (search.py:93-101) and `_fallback_session_id` (worker.py:55-63) are functionally identical, as are `_fallback_project` (worker.py:66-75) and the removed `_extract_project_from_path`. The constraint in requirements ("Does NOT import from scripts/history.py") doesn't apply here — both modules are in the `teleclaude` package and can share a common utility.

**Fix:** Extract shared transcript discovery logic (discover, extract session ID, extract project) into a shared module (e.g., `teleclaude/utils/transcript_discovery.py` or within `teleclaude/mirrors/store.py`). Both `teleclaude/history/search.py` and `teleclaude/mirrors/worker.py` import from it.

### 3. Missing tests for fan-out processor registry and event handler dispatch

**Location:** Tests directory — no test file for `teleclaude/mirrors/processors.py` or `teleclaude/mirrors/event_handlers.py`

The implementation plan (Task 4.1) lists "Test fan-out processor registry (register, dispatch, error isolation)" as checked, but no dedicated test exists. The existing tests cover the generator and worker end-to-end but don't exercise:
- `register_processor` / `get_processors` (registry API)
- `process_mirror_event` (processor logic with missing context, missing agent, etc.)
- `_dispatch` error isolation (one processor failing doesn't block others)
- `handle_agent_stop` / `handle_session_closed` (event-to-processor wiring)

**Fix:** Add a test file (`tests/unit/test_mirror_processors.py`) covering registry operations, dispatch with error isolation, and event handler wiring.

### 4. Out-of-scope behavioral change to session creation

**Location:** `teleclaude/core/db.py:348`, `teleclaude/core/command_handlers.py:280-285`

The `Db.create_session` default for `human_role` changed from `HUMAN_ROLE_ADMIN` to `None`. The `create_session` command handler now only applies the admin fallback for non-api/web origins. The deferrals.md explains this was needed to fix gate failures after merging main, and the comment in command_handlers.py explains the rationale. The behavioral change appears safe (api/web callers get role from boundary-injected identity instead of hardcoded admin), but it's outside the mirrors feature scope and deserves explicit confirmation that existing callers aren't affected.

**Action:** Confirm this change was intentional from the main merge and not a regression. If intentional, no code change needed — this is an awareness flag.

## Suggestions

### 5. Loose `db: object | None` parameter typing

**Location:** `teleclaude/mirrors/store.py` (all public functions)

The `db` parameter accepts `object | None` but actually handles `str`, `Path`, objects with `db_path` attribute, or `None`. A union type (`str | Path | None`) or a `Protocol` would communicate the contract more clearly and enable type checking.

### 6. Module-level mutable `_processors` list

**Location:** `teleclaude/mirrors/processors.py:29`

`_processors: list[MirrorProcessor] = []` is module-level mutable state. If tests register processors without cleanup, state leaks across tests. Consider adding a `_reset_processors()` function for test use, or documenting the expected singleton lifecycle.

### 7. `strict=False` in zip

**Location:** `teleclaude/history/search.py:264`

`zip(responses, resolved, strict=False)` — `asyncio.gather` with `return_exceptions=True` always returns the same count as inputs, so `strict=True` would be a stronger correctness assertion.

## Why No Issues at Critical Level

1. **Paradigm fit:** Mirror module follows the established pattern (migration, store, generator, worker, API routes) matching the memory observations precedent. API routes registered via `app.include_router()` like all other routers. Event wiring follows the agent_coordinator direct-handler and event_bus patterns.
2. **Requirements coverage:** All 15 success criteria have corresponding implementations and tests.
3. **Security:** SQL is fully parameterized. No secrets in code. Transcript path in API comes from daemon-controlled metadata, not external input. Auth middleware applies globally to API routes.
4. **Copy-paste duplication:** Checked. Duplicate transcript discovery (Finding #2) is flagged as Important. No other significant duplication.

## Fixes Applied

- **Finding 1:** Added the missing `history search --computer`, `history show --computer`, and `history show --raw` CLI flags and covered the CLI surface metadata with a regression test. Commit: `a9535963c`
- **Finding 2:** Extracted transcript discovery, fallback session-id parsing, and fallback project extraction into `teleclaude/utils/transcript_discovery.py`, then updated both history search and mirror reconciliation to import the shared helpers. Added unit coverage for agent-specific discovery rules. Commit: `342614876`
- **Finding 3:** Added `tests/unit/test_mirror_processors.py` to cover registry idempotence, processor skip paths, mirror generation dispatch, error isolation, and event-handler wiring. Commit: `652a184ce`
- **Finding 4:** Confirmed intentional. The `human_role=None` default and API/web fallback carve-out were introduced in merge-fix commit `1631c7a3d` (`fix(build): restore green repo gates`, dated March 7, 2026). Existing coverage in `tests/unit/test_access_control.py` verifies that API/web callers stay role-less unless a boundary injects a role, while non-API origins still retain the legacy admin fallback via `tests/unit/test_command_handlers.py`.

## Verdict

- [x] APPROVE
- [ ] REQUEST CHANGES
