# Review Findings: integrate-session-lifecycle-into-next-work

Review round: 2

## Paradigm-Fit Assessment

1. **Data flow**: `verify_artifacts()` follows established patterns — reads filesystem directly like `run_build_gates()` and `read_phase_state()`. Integrated at the correct point in `next_work()` (after build gates, before review dispatch). No inline hacks or bypassed data layers. Pass.
2. **Component reuse**: Reuses `PhaseName`, `PhaseStatus`, `REVIEW_APPROVE_MARKER` from existing codebase. New helpers `_extract_checklist_section` and `_is_review_findings_template` are justified — no existing section-extraction utilities exist. Pass.
3. **Pattern consistency**: POST_COMPLETION strings follow established step-by-step orchestrator instruction format. CLI handler follows existing `todo` subcommand patterns. `format_tool_call` `note` parameter properly rendered. Pass.

## Requirements Verification

- **R1** (Direct Peer Conversation): POST_COMPLETION["next-review"] splits into APPROVE/REQUEST CHANGES paths. Reviewer stays alive, fixer dispatched, `--direct` link established bidirectionally. Fallback path via standalone fix-review preserved with note in state machine. Existing `max_review_rounds` limit still applies. Pass.
- **R2** (Automated Artifact Verification): `verify_artifacts()` implemented with build/review phase checks. CLI command registered in `CLI_SURFACE` and routed in `_handle_todo`. Integrated into `next_work()` after `run_build_gates()`. Exit codes correct. Pass.
- **R3** (Session Lifecycle Principle): `next-work.md` includes `session-lifecycle.md` in required reads. POST_COMPLETION blocks have artifact verification before session end. Signal session concept for non-recoverable errors added across all POST_COMPLETION entries. Pass.

## Critical

None.

## Important

### I-1: Implementation plan tasks all unchecked (round 1, unfixed)

**Location**: `todos/integrate-session-lifecycle-into-next-work/implementation-plan.md`

All task checkboxes across all 5 phases remain `[ ]` (35 unchecked, 2 checked) despite `state.yaml` marking `build: complete` and code being fully implemented. The builder did not maintain artifact hygiene. This is self-contradictory: `verify_artifacts()` itself checks for unchecked tasks — meaning the build would fail its own verification gate.

Per review procedure step 8: "Ensure all implementation-plan tasks are checked; otherwise, add a finding and set verdict to REQUEST CHANGES."

This finding was raised in round 1 and has not been addressed (no commits since the REQUEST CHANGES verdict).

**Fix**: Mark all completed tasks as `[x]` in `implementation-plan.md`.

### I-2: Build Gates in quality-checklist.md all unchecked (round 1, unfixed)

**Location**: `todos/integrate-session-lifecycle-into-next-work/quality-checklist.md`, Build Gates section

All 9 Build Gates items remain `[ ]`. The builder did not complete the quality checklist despite the build being marked complete. `verify_artifacts()` checks for at least one `[x]` in this section — the build would fail its own gate.

Per review procedure step 9: "Validate Build section in quality-checklist.md is fully checked. If not, add a finding and set verdict to REQUEST CHANGES."

This finding was raised in round 1 and has not been addressed.

**Fix**: Complete the Build Gates checklist items that are satisfied.

### I-3: Fixer instructed to unilaterally update verdict to APPROVE

**Location**: `agents/commands/next-fix-review.md:54`

The fixer command instructs: "When all findings are resolved, update `review-findings.md` verdict to APPROVE and report FIX COMPLETE." The verdict is the reviewer's evaluative responsibility (per Reviewer concept). In the peer conversation model, the reviewer is separately instructed to update the verdict when satisfied (POST_COMPLETION["next-review"] step 4.e). Having both parties told to update creates role confusion — the fixer could approve their own work.

This was identified in the initial review round (prior to the round 1 REQUEST CHANGES) and has not been addressed.

**Fix**: Change the fixer instruction to: "When all findings are addressed, report FIX COMPLETE. The reviewer will verify and update the verdict."

## Suggestions

### S-1: `_extract_checklist_section` uses prefix matching

**Location**: `core.py` verify_artifacts calls with `"Build Gates"` and `"Review Gates"`

The function matches `"Build Gates"` against `## Build Gates (Builder)` via regex prefix matching. This works correctly today but is fragile — if a section like `## Build Gates Summary` were added, it would match. Consider using the full section name or adding a boundary assertion.

### S-2: POST_COMPLETION["next-fix-review"] lacks dual-path context

**Location**: `core.py` POST_COMPLETION["next-fix-review"] block

This block ends the session immediately (step 2), which is correct for the fallback path (reviewer already dead). But the instructions don't clarify this is the fallback path. In the peer conversation model, the orchestrator manages both sessions from POST_COMPLETION["next-review"] step 4. A brief inline comment would help future readers.

## Why No Critical Issues

1. **Paradigm-fit verified**: Data flow, component reuse, and pattern consistency all checked.
2. **Requirements validated**: All three requirements traced to specific code changes and confirmed per spec.
3. **Copy-paste duplication checked**: POST_COMPLETION entries share similar structure but are intentionally separate.
4. **Tests comprehensive**: 24 test cases covering pass/fail for both build and review phases, edge cases, and helper functions.
5. **Lint and type-check clean**: Per round 1 verification.

## Manual Verification Evidence

- Verified `verify_artifacts()` integration in `next_work()` — called after `run_build_gates()`, before review dispatch.
- Verified existing tests properly mock `verify_artifacts` to avoid regression.
- Verified CLI command registration and routing.
- Cannot manually test peer conversation flow (requires live sessions), but POST_COMPLETION instructions follow established dispatch-wait-read pattern.

## Verdict: REQUEST CHANGES

The code implementation is well-structured, follows established patterns, and has comprehensive test coverage. However, three Important findings block approval:

- **I-1 and I-2** are procedural hard gates (unchecked implementation plan and build checklist) that were raised in round 1 and remain unaddressed. No commits have been made since the round 1 REQUEST CHANGES verdict.
- **I-3** is a role-boundary issue in the fixer command that could lead to the fixer approving its own work, undermining the reviewer separation.

All three are straightforward fixes (checkbox marking and a single line change in next-fix-review.md).
