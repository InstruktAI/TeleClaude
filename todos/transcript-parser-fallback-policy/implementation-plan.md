# Implementation Plan: transcript-parser-fallback-policy

## Overview

Extract the duplicated "unknown agent → Claude" fallback logic into a single
`resolve_parser_agent()` function in `teleclaude/core/agents.py`, update all four
callsites to use it, add structured logging, and write comprehensive tests.

The approach is minimal: one new function, four callsite updates, one test file update.
No architectural changes, no new modules.

## Phase 1: Core Changes

### Task 1.1: Add `resolve_parser_agent()` to `teleclaude/core/agents.py`

**File(s):** `teleclaude/core/agents.py`

- [ ] Add function `resolve_parser_agent(active_agent: str | None) -> AgentName`
- [ ] If `active_agent` is `None` or empty string: log at `debug` level, return `AgentName.CLAUDE`
- [ ] If `AgentName.from_str()` succeeds: return the resolved value (no log)
- [ ] If `AgentName.from_str()` raises `ValueError`: log at `warning` level with the
      original value, return `AgentName.CLAUDE`
- [ ] Import `logging` and use module logger (`logger = logging.getLogger(__name__)`)

### Task 1.2: Update `teleclaude/api/streaming.py` `_get_agent_name()`

**File(s):** `teleclaude/api/streaming.py`

- [ ] Replace inline try/except in `_get_agent_name()` body with call to
      `resolve_parser_agent(session.active_agent)`
- [ ] Remove the `or "claude"` default — the resolver handles `None`

### Task 1.3: Update `teleclaude/api_server.py` `/messages` endpoint

**File(s):** `teleclaude/api_server.py`

- [ ] Replace inline try/except block (lines ~1096-1100) with call to
      `resolve_parser_agent(session.active_agent)`
- [ ] Import `resolve_parser_agent` from `teleclaude.core.agents`

### Task 1.4: Update `teleclaude/utils/transcript.py` `_get_entries_for_agent()`

**File(s):** `teleclaude/utils/transcript.py`

- [ ] The function already receives `AgentName` (enum), so no fallback change needed here.
      Verify that all callers pass a resolved `AgentName`, not a raw string. (This is
      already the case — callers resolve before calling.)
- [ ] No code change needed; this task is verification only.

### Task 1.5: Verify `get_transcript_parser_info()` safety

**File(s):** `teleclaude/utils/transcript.py`

- [ ] `get_transcript_parser_info()` takes `AgentName` enum, not a string. Since the enum
      is exhaustive, `KeyError` cannot happen if callers use `resolve_parser_agent()` first.
- [ ] Verify all callers pass `AgentName` enum values (not raw strings).
- [ ] No code change needed; this task is verification only.

---

## Phase 2: Validation

### Task 2.1: Tests

**File(s):** `tests/unit/test_agents.py`

- [ ] Add test `test_resolve_parser_agent_canonical_values` — parametrized over
      `("claude", AgentName.CLAUDE)`, `("codex", AgentName.CODEX)`, `("gemini", AgentName.GEMINI)`
- [ ] Add test `test_resolve_parser_agent_none_defaults_to_claude` — asserts
      `resolve_parser_agent(None) == AgentName.CLAUDE`
- [ ] Add test `test_resolve_parser_agent_empty_defaults_to_claude` — asserts
      `resolve_parser_agent("") == AgentName.CLAUDE`
- [ ] Add test `test_resolve_parser_agent_unknown_defaults_to_claude` — asserts
      `resolve_parser_agent("gpt4") == AgentName.CLAUDE`
- [ ] Add test `test_resolve_parser_agent_case_insensitive` — asserts
      `resolve_parser_agent(" CODEX ") == AgentName.CODEX`
- [ ] Add test `test_resolve_parser_agent_logs_warning_for_unknown` — captures log output,
      asserts warning contains original value
- [ ] Add test `test_resolve_parser_agent_logs_debug_for_none` — captures log output,
      asserts debug-level entry (not warning)
- [ ] Run `make test`

### Task 2.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
