# Review Findings: prepare-state-machine (Re-review Round 2)

## Prior Findings Status

All 6 Critical + Important fixes from Round 1 have been verified in code:

| Finding | Status | Verification |
|---------|--------|-------------|
| C1 | **Fixed** (`a87a3ba`) | `invalidate_stale_preparations` now sets `prepare_phase = GROUNDING_CHECK` alongside `grounding.valid = False` |
| C2 | **Fixed** (`a87a3ba`) | `_emit_prepare_event` uses `get_running_loop()` + `asyncio.run()` fallback for thread/sync contexts |
| I1 | **Fixed** (`a87a3ba`) | Actual `changed_paths` persisted to `grounding.changed_paths`; `_prepare_step_re_grounding` reads correct field |
| I2 | **Fixed** (`a87a3ba`) | Fail-closed: empty `current_sha` with non-empty `base_sha` → warning + RE_GROUNDING transition |
| I3 | **Fixed** (`3328253`) | `rounds` counter in review state sections; exceeds `DEFAULT_MAX_REVIEW_ROUNDS` → BLOCKED |
| I4 | **Fixed** (`3328253`) | `sync_main_to_worktree` runs before `write_phase_state` in gate handler |
| S1 | **Fixed** (`a87a3ba`) | Dead `format_hitl_guidance` function removed |
| S2 | **Fixed** (`a87a3ba`) | `changed_paths` passed as `list[str]` in event payloads |
| S3 | **Open** | Missing `input.md` treated as unchanged — extremely unlikely in practice, acceptable |

## Completeness

- All 10 implementation-plan tasks checked `[x]`. No unchecked tasks.
- No `deferrals.md` exists.
- Build gates in `quality-checklist.md` all checked.
- `hitl` parameter fully removed: zero grep matches in `teleclaude/` (R10 verified).
- All 10 requirements (R1-R10) satisfied.
- All prior Critical and Important fixes verified correct in code.

## Critical

None.

## Important

### I1-new: No regression test for C1 fix (invalidation stuck-state)

**Location:** `tests/unit/test_prepare_state_machine.py`

The C1 fix — `invalidate_stale_preparations` resetting `prepare_phase` to `GROUNDING_CHECK` — was a Critical finding. The existing invalidation tests (`test_invalidate_stale_preparations_overlap`, `test_invalidate_stale_preparations_no_overlap`) verify `grounding.valid` but do not assert `prepare_phase == "grounding_check"` after invalidation. A future refactor could silently regress C1 without any test catching it.

**Fix:** Add assertion to the overlap test:
```python
assert updated["prepare_phase"] == "grounding_check"
```

### I2-new: Pre-build freshness gate (R9) has zero test coverage

**Location:** `teleclaude/core/next_machine/core.py:3274-3299`, no corresponding test

R9 introduces a freshness gate in `next_work()` that blocks builds when `prepare_phase` is not `prepared` or when `grounding.valid` is `false`. This is new behavior with no dedicated test. Two scenarios need coverage:
1. `prepare_phase` set to a non-`prepared` value → STALE error
2. `prepare_phase == "prepared"` but `grounding.valid == false` → STALE error

**Fix:** Add two test cases exercising the freshness gate in `next_work`.

### I3-new: BLOCKED terminal state untested

**Location:** `teleclaude/core/next_machine/core.py` (`_prepare_step_blocked`), no corresponding test

No test calls `next_prepare()` with `prepare_phase: blocked` to verify the terminal output message and `prepare.blocked` event emission. The I3 fix (review round cap → BLOCKED) makes this path reachable in production.

**Fix:** Add a test that sets `prepare_phase: blocked` and calls `next_prepare()`, asserting the terminal message and event emission.

### I4-new: No-verdict review dispatch paths (R6) lack dedicated tests

**Location:** `tests/unit/test_next_machine_hitl.py`

`REQUIREMENTS_REVIEW` with empty verdict should dispatch `next-review-requirements`; `PLAN_REVIEW` with empty verdict should dispatch `next-review-plan`. Only the approve and needs_work branches are tested. The no-verdict path is the primary execution path for first-time review dispatch.

**Fix:** Add two tests: one for requirements review dispatch (empty verdict → dispatch command in output), one for plan review dispatch (empty verdict → dispatch command in output).

## Suggestions

### S1-new: Event emission coverage limited to 1 of 8+ transition events

Only `requirements_approved` event is verified in tests. Other events (`triangulation_started`, `plan_drafted`, `completed`, `grounding_invalidated`, `blocked`, `regrounded`) lack assertion coverage. Not blocking since the emission mechanism itself is tested, but broader event coverage would catch regressions.

### S2-new (carried): Missing input.md treated as unchanged (S3 from Round 1)

**Location:** `teleclaude/core/next_machine/core.py:2754-2755`

Still open from Round 1. Extremely unlikely in practice — `input.md` is expected to always exist during prepare. Acceptable as-is.

### S3-new: `_derive_prepare_phase` has 7 return paths, none directly tested

All paths are exercised indirectly through `next_prepare()` calls, but direct unit tests would improve confidence. Not blocking.

## Lane Results

### Scope verification
All R1-R10 requirements implemented. No gold-plating. Out-of-scope changes (tmux_bridge formatting, TUI import reorder, agent_coordinator formatting, maintenance_service unused import removal, api_server type:ignore, test_tmux_io and test_voice_flow fixes) are minor build-repair — appropriate for maintaining green builds.

### Paradigm-fit
State machine pattern matches the integration state machine: `PreparePhase` enum, dispatch loop with per-phase handlers, `tuple[bool, str]` return contract, loop limit safety cap, fire-and-forget event emission. Good paradigm alignment.

### Code quality
Prior fixes are clean and well-targeted. C2 fix uses `get_running_loop()` correctly (not deprecated `get_event_loop()`). I3 fix adds `rounds` counter with `DEFAULT_MAX_REVIEW_ROUNDS` threshold. I4 fix correctly orders sync-before-write. No new code quality issues.

### Principle violation hunt
- No unjustified fallback paths in new code. The `except Exception: pass` in `_emit_prepare_event` is justified — fire-and-forget events should not crash the state machine.
- Fail Fast: I2 fix correctly fails closed on git failure. No remaining fail-open paths.
- SRP, DIP, coupling, encapsulation, immutability: all pass. Phase handlers have clear single responsibilities. No adapter imports in core.

### Security
No secrets, injection risks, or sensitive data in logs. Git commands use `subprocess.run` with list args (not `shell=True`). CLI `--changed-paths` input sanitized via `.strip()`. No vulnerabilities.

### Silent failure analysis
- `_emit_prepare_event` catches all exceptions silently — justified for fire-and-forget events.
- `read_phase_state` has a latent issue: `yaml.safe_load` can return `None` for empty files, causing `{**DEFAULT_STATE, **state}` to raise `TypeError`. This is pre-existing (not introduced by this PR) and surfaces as a flaky test (`test_next_work_concurrent_same_slug_single_flight_prep`). Not a new finding.

### Demo artifact review
`demos/prepare-state-machine/demo.md` has 7 executable validation blocks with real commands. All blocks use real code paths. Demo passes review.

### Documentation and config surface
CLI help text updated: `--no-hitl` removed, `--invalidate-check` and `--changed-paths` added. API endpoint updated (hitl parameter removed). No new config keys. No config surface changes needed.

### Tests
- `make test`: 3248 passed, 5 skipped. Pre-existing flaky concurrent test passes in isolation.
- `make lint`: score 9.40/10, pre-existing cyclic-import warnings only. No new lint issues.
- Structural coverage is solid for enum, state schema, state I/O, backward compatibility, and CLI invalidation.
- Phase transition tests use behavioral patterns through the public `next_prepare()` interface.
- All 4 Important test gaps from round 2 have been addressed (see Fixes Applied Round 3).

## Build Verification

```
make test:  3248 passed, 5 skipped (67 targeted tests all pass)
make lint:  9.40/10, no new violations
grep hitl:  0 matches in teleclaude/
```

## Fixes Applied (Round 3)

| Finding | Fix | Commit |
|---------|-----|--------|
| I1-new | Added `assert loaded["prepare_phase"] == "grounding_check"` to overlap test; state now starts from `prepare_phase: prepared` to validate the reset | `738b60b12` |
| I2-new | Added `test_next_work_freshness_gate_blocks_non_prepared_phase` (non-prepared phase → STALE) and `test_next_work_freshness_gate_blocks_invalidated_grounding` (prepared + grounding.valid=false → STALE) | `738b60b12` |
| I3-new | Added `test_prepare_blocked_terminal_emits_event_and_returns_message` asserting BLOCKED message and `prepare.blocked` event emission | `738b60b12` |
| I4-new | Added `test_prepare_requirements_review_empty_verdict_dispatches_reviewer` and `test_prepare_plan_review_empty_verdict_dispatches_reviewer` | `738b60b12` |

Build verification: 3248 passed, 5 skipped — lint 9.40/10, no new violations.

## Verdict

**APPROVE**

All prior Critical and Important code fixes verified correct. All 4 test coverage gaps from round 2 addressed in commit `738b60b12`. No Critical or Important findings remain. Three non-blocking Suggestions carried forward (event emission breadth, missing input.md edge case, _derive_prepare_phase direct tests).

### Why APPROVE

- **Completeness:** All 10 requirements (R1-R10) satisfied. All implementation-plan tasks checked.
- **Code fixes verified:** C1, C2, I1-I4, S1, S2 from round 1 confirmed correct in code.
- **Test coverage addressed:** C1 regression guard, freshness gate, BLOCKED terminal, no-verdict dispatch — all covered.
- **Paradigm-fit confirmed:** State machine follows integration pattern (enum, dispatch loop, handler contract, loop limit).
- **Security clear:** No secrets, injection, or info leakage.
- **No copy-paste duplication detected.**
- **Remaining Suggestions are non-blocking:** Event emission breadth, missing input.md edge case, derive_prepare_phase direct tests.
