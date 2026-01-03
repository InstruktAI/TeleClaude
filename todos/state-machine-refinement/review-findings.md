# Code Review: state-machine-refinement

**Reviewed**: January 3, 2026
**Reviewer**: Codex

## Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| R1: Remove bug check from `next_work()` | ✅ Implemented | Bug check block removed. |
| R2: Introduce ready state `[.]` | ⚠️ Partial | Ready state supported in code, but roadmap legend not updated. |
| R3: State machine owns checkbox transitions | ✅ Implemented | `next_prepare()`/`next_work()` update roadmap state. |
| R4: Add `todos/dependencies.json` support | ✅ Implemented | Read/write helpers added; file created on first write. |
| R5: Add `teleclaude__set_dependencies()` tool + validation | ⚠️ Partial | Existence validation is substring-based; can accept non-existent slugs. |
| R6: `resolve_slug()` ready-only + dependency gating | ⚠️ Partial | Dependency gating is outside `resolve_slug`; explicit slugs bypass deps. |
| R7: `update_roadmap_state()` helper | ✅ Implemented | Added with git commit side effect. |
| Tests per requirements | ❌ Missing | No new unit/integration tests added. |

## Critical Issues (must fix)

- None found.

## Important Issues (should fix)

- [code] `teleclaude/mcp_server.py:2561` - `teleclaude__set_dependencies()` validates slug/deps with substring checks (`if slug not in content`), so `auth` passes when only `auth-system` exists or when legend text contains the slug. This violates the strict roadmap validation requirement.
  - Suggested fix: Parse roadmap items with a regex like `r"^- \[[ .>x]\] ([a-z0-9-]+)"` and compare exact slugs.
- [code] `teleclaude/mcp_server.py:2534` - New import inside method violates the project's “imports at module level” rule and may fail linting.
  - Suggested fix: move `detect_circular_dependency`, `read_dependencies`, and `write_dependencies` imports to top-level and resolve circular dependency (e.g., by refactoring helpers into a shared module).
- [code] `teleclaude/core/next_machine.py:863` - Explicit slug path bypasses dependency checks; callers can work on items with unsatisfied dependencies.
  - Suggested fix: when `slug` is provided, call `check_dependencies_satisfied(...)` and return a clear dependency error if blocked.
- [code] `teleclaude/core/next_machine.py:882` - Ready-item detection uses `if "[.]" in content`, which can match the status legend or description text and incorrectly returns `DEPS_UNSATISFIED` when no ready items exist.
  - Suggested fix: use the same ready-item regex and track a `has_ready_items` flag based on actual matches.
- [tests] `tests/` - Required unit/integration tests are missing (no new/updated test files in this change).
  - Suggested fix: add the tests listed in `todos/state-machine-refinement/requirements.md` and update coverage for new dependency logic and roadmap state transitions.
- [comments] `todos/roadmap.md` - Status legend still lacks `[.]` (Ready) entry, so the documented roadmap format is now out of sync.
  - Suggested fix: update the legend line to include `[.] = Ready`.

## Suggestions (nice to have)

- [simplify] `teleclaude/core/next_machine.py:287` - `resolve_slug(..., ready_only=True)` duplicates selection logic but does not enforce dependencies. Consider centralizing dependency gating here so `next_work()` can reuse it and avoid divergent behavior.
- [code] `todos/state-machine-refinement/state.json` - This looks like a work-state artifact; confirm whether it should live in the main tree or be generated in a worktree instead.

## Strengths

- Dependency helpers and roadmap state update are cleanly factored and follow the intended workflow.
- Error messages for no-ready-items and dependency blocking are clear and actionable.

---

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

### If REQUEST CHANGES:

Priority fixes needed:
1. Enforce roadmap slug existence with exact slug matching in `teleclaude__set_dependencies()`.
2. Add the required unit/integration tests for roadmap state and dependency logic.
3. Ensure dependency checks apply even when an explicit slug is provided.

---

## Fixes Applied

| Issue | Fix | Commit |
|-------|-----|--------|
| Substring-based slug validation in `teleclaude__set_dependencies()` | Changed to exact regex matching with `r"^-\s+\[[. >x]\]\s+([a-z0-9-]+)"` | e0b6426 |
| Imports inside method violating module-level rule | Moved `detect_circular_dependency`, `read_dependencies`, `write_dependencies` to top-level imports | e0b6426 |
| Explicit slug bypasses dependency checks in `next_work()` | Added `check_dependencies_satisfied()` call before using explicit slug | e0b6426 |
| Ready-item detection using substring match | Changed to regex-based detection with `pattern.search(content)` | e0b6426 |
| Roadmap legend missing `[.]` entry | Already present - no fix needed (false positive in review) | N/A |
| Missing unit/integration tests | Added comprehensive test suite covering all requirements | 8a6acfb |
