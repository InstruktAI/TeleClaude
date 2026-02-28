# Review Findings: integrate-session-lifecycle-into-next-work

## Paradigm-Fit Assessment

1. **Data flow**: `verify_artifacts()` follows established patterns — reads filesystem directly like `run_build_gates()` and `read_phase_state()`. Integrated at the correct point in `next_work()` (after build gates, before review dispatch). No inline hacks or bypassed data layers. Pass.
2. **Component reuse**: Reuses `PhaseName`, `PhaseStatus`, `REVIEW_APPROVE_MARKER` from existing codebase. New helpers `_extract_checklist_section` and `_is_review_findings_template` are justified — no existing section-extraction utilities exist. Pass.
3. **Pattern consistency**: POST_COMPLETION strings follow established step-by-step orchestrator instruction format. CLI handler follows existing `todo` subcommand patterns (`_handle_todo_verify_artifacts` mirrors `handle_todo_mark_phase` structure). `format_tool_call` `note` parameter properly rendered. Pass.

## Requirements Verification

- **R1** (Direct Peer Conversation): POST_COMPLETION["next-review"] splits into APPROVE/REQUEST CHANGES paths. Reviewer stays alive, fixer dispatched, `--direct` link established bidirectionally. Fallback path via standalone fix-review preserved with note in state machine. Existing `max_review_rounds` limit still applies via state machine routing. Pass.
- **R2** (Automated Artifact Verification): `verify_artifacts()` implemented with build/review phase checks (checkboxes, commits, findings, verdict, quality checklist sections). CLI command registered in `CLI_SURFACE` and routed in `_handle_todo`. Integrated into `next_work()` after `run_build_gates()`. Exit codes correct (0 pass, 1 fail). Pass.
- **R3** (Session Lifecycle Principle): `next-work.md` includes `session-lifecycle.md` in required reads. POST_COMPLETION blocks have artifact verification before session end. Signal session concept for non-recoverable errors added across all POST_COMPLETION entries. Pass.

## Critical

None.

## Important

### I-1: Implementation plan tasks all unchecked

**Location**: `todos/integrate-session-lifecycle-into-next-work/implementation-plan.md`

All task checkboxes across all 5 phases remain `[ ]` despite `state.yaml` marking `build: complete`. The implementation IS present in code, but the artifact hygiene was not maintained by the builder. This is self-contradictory: `verify_artifacts()` itself checks for unchecked tasks in `implementation-plan.md` — meaning the build would fail its own verification gate.

Per review procedure: "Ensure all implementation-plan tasks are checked; otherwise, add a finding and set verdict to REQUEST CHANGES."

**Fix**: Mark all completed tasks as `[x]` in `implementation-plan.md`.

### I-2: Build Gates in quality-checklist.md all unchecked

**Location**: `todos/integrate-session-lifecycle-into-next-work/quality-checklist.md`, Build Gates section

All 9 Build Gates items remain `[ ]`. The builder did not complete the quality checklist despite the build being marked complete. `verify_artifacts()` checks for at least one `[x]` in this section — again, the build would fail its own gate.

Per review procedure: "Validate Build section in quality-checklist.md is fully checked. If not, add a finding and set verdict to REQUEST CHANGES."

**Fix**: Complete the Build Gates checklist items that are satisfied (tests pass, lint passes, code committed, etc.).

### I-3: Fixer instructed to unilaterally update verdict to APPROVE

**Location**: `agents/commands/next-fix-review.md:54`, `core.py` POST_COMPLETION["next-review"] step 4.e

Both the fixer command and POST_COMPLETION tell the fixer: "update `review-findings.md` verdict to APPROVE." The verdict is the reviewer's evaluative responsibility. The reviewer is separately told (step 4.e) to update the verdict when satisfied. Having both parties told to update creates role confusion — the fixer could approve their own work.

**Fix**: Change the fixer instruction in `next-fix-review.md` to: "When all findings are addressed, report FIX COMPLETE. The reviewer will verify and update the verdict." Remove the verdict-update instruction from the fixer's message in POST_COMPLETION step 4.f as well.

## Suggestions

### S-1: `_extract_checklist_section` uses prefix matching

**Location**: `core.py:525` (function), called at lines 667 and 710

The function matches `"Build Gates"` against `## Build Gates (Builder)` via regex prefix. `re.match` succeeds because it only requires start-of-string match. This works today but is fragile — a future `## Build Gates Summary` section would match unintentionally. Consider passing the full section name `"Build Gates (Builder)"` / `"Review Gates (Reviewer)"` or adding a word boundary after the name.

### S-2: POST_COMPLETION["next-fix-review"] lacks fallback-path context

**Location**: `core.py:209-218`

The `next-fix-review` POST_COMPLETION block ends the session immediately (step 2) and resets review to pending (step 3). This is correct for the fallback path (reviewer already dead), but the instructions don't clarify this. The state machine note at line 3040 tells the orchestrator to prefer the direct conversation pattern when the reviewer is alive, but an orchestrator following `next-fix-review`'s POST_COMPLETION won't see that note. A brief comment would prevent confusion.

### S-3: Missing test for subprocess failure path

**Location**: `tests/unit/core/test_next_machine_verify_artifacts.py`

The `verify_artifacts` build phase handles `subprocess.TimeoutExpired` and `OSError` at line 656-658, but no test exercises this branch. Similarly, the `merge-base` failure fallback (lines 643-650) is untested. Both are legitimate edge cases worth covering.

### S-4: git log failure silently classified as "no commits"

**Location**: `core.py:642, 650`

If `git log` fails (non-zero returncode, output to stderr only), the code reads empty stdout and treats it as "no commits found" rather than "git error." Consider checking `log_result.returncode` before interpreting stdout.

## Why No Critical Issues

1. **Paradigm-fit verified**: Data flow, component reuse, and pattern consistency all checked. No copy-paste duplication, no bypassed data layers.
2. **Code quality is solid**: `verify_artifacts()` is well-structured with clear separation of phase-specific checks, proper error handling for YAML parsing, and subprocess timeouts.
3. **Tests comprehensive**: 24 unit test cases covering pass/fail for both phases, edge cases (missing files, malformed YAML, templates), and helper functions. 2450 tests pass (0 failures). Existing tests properly mock `verify_artifacts` to avoid regression.
4. **The I-1/I-2 findings are clerical, not code quality issues**: The implementation is correct and complete — the builder simply didn't maintain the artifact checklists.

## Manual Verification Evidence

- Verified `telec todo verify-artifacts` CLI command registration in `CLI_SURFACE` dict and routing in `_handle_todo`.
- Verified `verify_artifacts()` integration point in `next_work()` — called after `run_build_gates()` passes, before review dispatch.
- Verified existing tests (`test_next_machine_hitl.py`, `test_next_machine_state_deps.py`) properly mock `verify_artifacts` with correct patch target.
- Verified `subprocess.run` mock in tests uses correct target: `core.py` does `import subprocess` (module-level) and calls `subprocess.run(...)`, so `patch("subprocess.run")` patches the shared module attribute correctly.
- Full test suite run: 2450 passed, 106 skipped, 0 failures.
- Cannot manually test peer conversation flow (requires live session infrastructure), but code inspection confirms POST_COMPLETION instructions follow established dispatch-wait-read pattern.

## Verdict: REQUEST CHANGES

The code implementation is well-structured and all requirements are addressed. However, I-1 (unchecked implementation plan) and I-2 (unchecked build gates) are mandatory REQUEST CHANGES triggers per the review procedure. I-3 (fixer verdict confusion) is a design issue that should also be addressed to prevent role confusion in the peer conversation model. All three are straightforward fixes.
