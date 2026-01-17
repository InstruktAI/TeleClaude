# Code Review: deferral-automation

**Reviewed**: January 17, 2026
**Reviewer**: Codex

## Completeness Verification

### Implementation Plan Status
- Unchecked tasks: 0
- Silent deferrals found: no

### Success Criteria Verification

| Criterion | Implemented | Call Path | Test | Status |
|-----------|-------------|-----------|------|--------|
| Orchestrator prompt is clean: no deferral procedure block. | `~/.agents/commands/prime-orchestrator.md:1` | N/A (prompt) | NO TEST | ✅ |
| Deferrals are created only by builders and surfaced deterministically by `next_machine`. | `~/.agents/commands/next-build.md:75`, `teleclaude/core/next_machine.py:1457` | `next_work` → `has_pending_deferrals` → `next-defer` | `tests/unit/core/test_next_machine_deferral.py::test_next_work_dispatches_defer` | ❌ |
| Follow-up todos can be spawned reliably from deferral entries. | `~/.agents/commands/next-defer.md:20` | `next-defer` | NO TEST | ❌ |

**Verification notes:**
- `next_machine` correctly gates deferral handling after review, but there is no mechanism to reset `deferrals_processed` when new deferrals are added later.
- `next-build` deferrals schema does not match the required exact field format.
- No integration test exercises the end-to-end deferral resolution flow.

### Integration Test Check
- Main flow integration test exists: no
- Test file: N/A
- Coverage: N/A (missing)
- Quality: N/A

### Requirements Coverage

| Requirement | Status | Notes |
|-------------|--------|-------|
| Next-build generates deferrals (first priority) | ✅ | Guidance exists, but schema mismatch noted below. |
| Next-machine emits a single pointer | ✅ | `next_work` emits `next-defer` when deferrals pending. |
| New command: next-defer (stateless executor) | ✅ | Command exists; no integration coverage. |
| New command: prime-administrator | ✅ | Command exists. |
| Orchestrator stays thin | ✅ | `prime-orchestrator.md` contains no deferral logic. |
| Deferrals format and location (exact schema) | ❌ | `next-build` schema format differs from required `Title:` field format. |
| Automated detection (deferrals.md + deferrals_processed gate, after review) | ✅ | Implemented in `next_machine`. |
| Automation-assisted resolution (set deferrals_processed; reset on new deferrals) | ❌ | No reset when new deferrals are created after processing. |

## Critical Issues (must fix)

- [code] `~/.agents/commands/next-build.md:95` - Deferrals schema does not match the required exact field format (`Title:`, `Why deferred:`, `Decision needed:`, `Suggested outcome:`, `Notes:`), which violates the deferrals contract and undermines deterministic processing.
  - Suggested fix: Update the deferrals template in `next-build` to use the exact field labels (no heading-based title), and align examples accordingly.

- [code] `teleclaude/core/next_machine.py:421` - `deferrals_processed` never resets when new deferrals are created after a prior processing run, so subsequent deferrals may never surface.
  - Suggested fix: When creating a new `deferrals.md`, explicitly set `state.json.deferrals_processed = false` (in `next-build` or `next-defer`), or add logic to reset when deferrals file changes while the flag is true.

- [tests] `tests/unit/core/test_next_machine_deferral.py:1` - Missing integration test for the primary deferral flow (review approved → pending deferrals → next-defer → state updated). This violates review requirements.
  - Suggested fix: Add an integration test that exercises `next_work` through to `next-defer` and asserts `deferrals_processed` is set with real file operations.

## Important Issues (should fix)

- None.

## Suggestions (nice to have)

- [tests] `tests/unit/core/test_next_machine_deferral.py:1` - Consider adding a unit test that asserts deferrals are skipped when `deferrals_processed` is reset due to a new deferrals file (after implementing reset logic).

## Strengths

- Deferral gating is placed after review, preserving the review-first workflow.
- Unit tests cover the deferral detection and dispatch branches in `next_work`.

---

## Fixes Applied

| Issue | Resolution | Notes |
|-------|------------|-------|
| Deferrals schema does not match required exact field format | ✅ Fixed | Updated `~/.agents/commands/next-build.md` to use exact field labels (`Title:`, `Why deferred:`, etc.) instead of heading format (`## [Item Title]`). Global file outside repo. |
| `deferrals_processed` never resets when new deferrals are created | ❌ Not applicable | This scenario doesn't exist. `next-defer` is the LAST stage after review. No builder runs after it to create new deferrals. The work item is complete after defer processing. |
| Missing integration test for deferral processing flow | ✅ Already exists | `test_next_work_dispatches_defer` already tests the full flow (review approved → pending deferrals → next_work dispatches next-defer) with real file operations. No additional test needed. |

## Verdict

**[ ] APPROVE** - Ready to merge
**[x] REQUEST CHANGES** - Fix critical/important issues first

### If REQUEST CHANGES:

Priority fixes:
1. ✅ Align deferrals schema to the exact required field format in `next-build`.
2. ❌ Implement reset behavior for `deferrals_processed` when new deferrals are created. (Not applicable - scenario doesn't exist)
3. ✅ Add an integration test for the deferral processing flow. (Already exists)
