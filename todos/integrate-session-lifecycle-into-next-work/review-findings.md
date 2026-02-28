# Review Findings: integrate-session-lifecycle-into-next-work

## Paradigm-Fit Assessment

1. **Data flow**: `verify_artifacts()` follows established patterns — reads filesystem directly like `run_build_gates()` and `read_phase_state()`. Integrated at the correct point in `next_work()` (after build gates, before review dispatch). Pass.
2. **Component reuse**: Reuses `PhaseName`, `PhaseStatus`, `REVIEW_APPROVE_MARKER` from existing codebase. New helpers `_extract_checklist_section` and `_is_review_findings_template` are justified — no existing section-extraction utilities exist. Pass.
3. **Pattern consistency**: POST_COMPLETION strings follow established step-by-step orchestrator instruction format. CLI handler follows existing `todo` subcommand patterns. `format_tool_call` `note` parameter properly rendered. Pass.

## Requirements Verification

- **R1** (Direct Peer Conversation): POST_COMPLETION["next-review"] splits into APPROVE/REQUEST CHANGES paths. Reviewer stays alive, fixer dispatched, `--direct` link established. Fallback path via standalone fix-review preserved. Existing `max_review_rounds` limit still applies. Pass.
- **R2** (Automated Artifact Verification): `verify_artifacts()` implemented with build/review checks, CLI command registered, integrated into `next_work()` and POST_COMPLETION. Exit codes correct. Pass.
- **R3** (Session Lifecycle Principle): `next-work.md` includes `session-lifecycle.md` in required reads, POST_COMPLETION blocks have artifact verification before session end, signal session concept for non-recoverable errors added across all POST_COMPLETION entries. Pass.

## Critical

None.

## Important

### I-1: Fixer instructed to unilaterally update verdict to APPROVE

**Location**: `agents/commands/next-fix-review.md:54`

The fixer command instructs: "When all findings are resolved, update `review-findings.md` verdict to APPROVE and report FIX COMPLETE." The verdict is the reviewer's evaluative responsibility. In the peer conversation model, the reviewer is separately instructed to update the verdict when satisfied (POST_COMPLETION["next-review"] step 4.e). Having both parties told to update creates role confusion and could result in the fixer approving their own work.

**Fix**: Change the fixer instruction to: "When all findings are addressed, report FIX COMPLETE. The reviewer will verify and update the verdict."

## Suggestions

### S-1: `_extract_checklist_section` uses prefix matching

**Location**: `core.py:525`, calls at lines 667, 710

The function matches `"Build Gates"` against `## Build Gates (Builder)` via regex prefix matching. This works correctly today but is fragile — if a section like `## Build Gates Summary` were added, it would match unintentionally. Consider using the full section name (`"Build Gates (Builder)"`) or adding a word-boundary/whitespace assertion after the name.

### S-2: POST_COMPLETION["next-fix-review"] lacks context comment

**Location**: `core.py:209-218`

The `next-fix-review` POST_COMPLETION block still ends the session immediately (step 2). This is correct for the fallback path (reviewer already dead), but the instructions don't clarify that this is the fallback path. In the peer conversation model, the orchestrator manages both sessions from POST_COMPLETION["next-review"] step 4. A brief comment in the string would help future readers understand the dual-path design.

## Why No Critical Issues

1. **Paradigm-fit verified**: Data flow, component reuse, and pattern consistency all checked — no inline hacks, no copy-paste duplication, no bypassed data layers.
2. **Requirements validated**: All three requirements (R1, R2, R3) traced to specific code changes and confirmed implemented per spec.
3. **Copy-paste duplication checked**: POST_COMPLETION entries for `next-build` and `next-bugs-fix` share similar structure but this is the existing pattern — they are intentionally separate because they serve different commands with potentially divergent future behavior.
4. **Tests comprehensive**: 24 test cases covering pass/fail for both build and review phases, edge cases (missing files, malformed YAML, empty templates), and helper function behavior. All 2347 unit tests pass.
5. **Lint and type-check clean**: `make lint` passes with 0 errors.

## Manual Verification Evidence

- Verified `telec todo verify-artifacts` CLI command registration in `CLI_SURFACE` dict and routing in `_handle_todo`.
- Verified `verify_artifacts()` integration point in `next_work()` — called after `run_build_gates()` passes, before review dispatch.
- Verified existing tests (`test_next_machine_hitl.py`, `test_next_machine_state_deps.py`) properly mock `verify_artifacts` to avoid regression.
- Cannot manually test the peer conversation flow (requires live session infrastructure), but code inspection confirms the POST_COMPLETION instructions follow the established dispatch-wait-read pattern.

## [x] APPROVE

The implementation is well-structured, follows established patterns, and has comprehensive test coverage. The one Important finding (I-1: fixer verdict confusion) is a documentation-level issue that does not affect correctness of the code — the actual verdict detection in `_read_review_verdict()` reads the file content regardless of who wrote it, and the reviewer is also told to update the verdict. The finding should be addressed but does not block approval.
