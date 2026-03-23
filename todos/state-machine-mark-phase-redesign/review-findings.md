# Review Findings: state-machine-mark-phase-redesign (Re-review)

**Ad-hoc review (via from-main)** — stub requirements and implementation plan. Scope and demo lanes skipped. All other lanes executed.

---

## Prior Findings Status

All 12 findings from the initial review (C-1 through C-3, I-1 through I-9) have been verified as correctly fixed. See "Fixes Applied" table below for commit references.

---

## Resolved During Review

The following were fixed inline during this re-review pass:

- **R4** `work_lifecycle.py:181,206` — `_on_enter_review_changes` and `_on_enter_review_approved` used `ctx.cwd` (always project root via `resolve_canonical_project_root` in `state_io.py:255`) for `get_head_commit()` and `_extract_finding_ids()`. This stamped `review_baseline_commit` with main's HEAD instead of the worktree branch HEAD. Downstream, `_repair_stale_review_approval` in `work.py:554-557` compares this baseline against the worktree HEAD — since main's HEAD != branch HEAD, approval was always invalidated, producing an infinite review loop. Fixed by constructing `worktree_cwd = str(Path(ctx.cwd) / WORKTREE_DIR / ctx.slug)` before calling `get_head_commit` and `_extract_finding_ids` — the same pattern used by `_on_enter_finalize_ready` at line 225.

---

## Critical

_(none unresolved)_

---

## Important

### I-10 — `_on_enter_review_changes` and `_on_enter_review_approved` have no direct unit tests

**File:** `tests/unit/core/next_machine/test_work_lifecycle.py`

The review handler functions are only exercised via mock side-effects in `test_state_io.py` (lines 88-113, 128-154), where `_target_side_effect` simulates handler behavior without calling the real code. The actual handlers — which perform `get_head_commit`, `_extract_finding_ids`, `review_round` bumping, and findings merging — are never tested directly. The critical bug fixed in R4 would have been caught by a direct handler test asserting that `get_head_commit` receives the worktree path, not `ctx.cwd`.

`_on_enter_finalize_ready` and `_on_enter_finalize_handoff` have thorough direct unit tests in `test_work_lifecycle.py` (added for I-1). The review handlers should follow the same pattern.

**Required:** Add direct unit tests for `_on_enter_review_changes` and `_on_enter_review_approved` covering:

- Happy path: `review_round` incremented, `review_baseline_commit` stamped from worktree HEAD, findings extracted
- `get_head_commit` returns empty -> warning logged, `review_baseline_commit` not stamped
- `_on_enter_review_approved`: unresolved findings merged into resolved

---

### I-11 — No backward-transition guard in `StateMachine.target()`

**File:** `teleclaude/core/next_machine/state_machine.py:74-80`

The engine checks for exact-match idempotency (`source == target_name`) but has no guard against backward state movement. If the current state is `finalize_handed_off` and a retry calls `mark_phase("finalize_ready")`, the engine will execute the backward transition, call `_on_enter_finalize_ready`, and overwrite the finalize dict — regressing state from `handed_off` to `ready`.

Backward movement IS intentionally used: `_repair_stale_review_approval` in `work.py:563` calls `mark_phase(worktree_cwd, slug, "review_pending")` to move from `review_approved` back to `review_pending`. So a blanket forward-only guard would break the repair path.

The engine delegates all validation to on_enter handlers, which is a valid design choice. However, `_on_enter_finalize_ready` does not check whether the state has already advanced past `finalize_ready` — it only validates worktree/HEAD/remote parity. A retry after handoff would pass all those checks and silently regress.

**Required:** Either (a) add a state-ordering guard to the handler (`if current state is past finalize_ready, raise`), or (b) document explicitly that backward movement is by-design and audit all callers that could trigger unintentional regression.

---

### I-12 — `_on_enter_prepared` grounding marked `valid: True` when git command fails

**File:** `teleclaude/core/next_machine/work_lifecycle.py:156-165`

When `run_git_command(["rev-parse", "HEAD"])` fails (`rc != 0`), the grounding dict is still set to `"valid": True` with no `base_sha`. This is an internally contradictory state: grounding claims to be valid but has no baseline to ground against. Downstream grounding checks that rely on `grounding["valid"]` will trust this state and skip re-grounding, even though there is no SHA to compare against — silently defeating the staleness detection.

**Required:** Set `"valid": False` when `rc != 0`, or raise `ValueError` since a git failure during prepare is a real infrastructure problem.

---

## Suggestions

### S-1 — `StateMachine._state_index` returns `-1` for unknown state

**File:** `teleclaude/core/next_machine/state_machine.py:117-122`

`_state_index` returns `-1` (a valid Python list index) for unknown state names instead of raising. Consider raising `ValueError` to match `_lookup_state` semantics, or explicitly documenting the `-1` sentinel contract. Note: `_state_index` and `state_names` are currently unused — if I-11 is resolved without adding a state-ordering guard to the engine, these should be removed as dead code.

_(Carried from initial review — optional.)_

---

### S-2 — `session_identity.py` corrupt file returns `None` without logging

**File:** `teleclaude/session_identity.py:25-39, 110-133`

`_read_field` silently returns `None` on `json.JSONDecodeError` (corrupt identity file). `_write_identity_fields` silently discards the existing file on `json.JSONDecodeError` during the read-merge step. Both paths can mask data-loss scenarios with no log trail.

_(Carried from initial review — optional.)_

---

### S-3 — Finalize handlers use `datetime.now()` instead of `ctx.at`

**File:** `teleclaude/core/next_machine/work_lifecycle.py:255, 273`

`_on_enter_finalize_ready` and `_on_enter_finalize_handoff` call `datetime.now(UTC).isoformat()` for `ready_at`/`handed_off_at` instead of using `ctx.at`. The `_on_enter_prepared` handler correctly uses `ctx.at`. This creates a minor timestamp inconsistency: the finalize dict timestamps will differ from the history entry's `at` value by the execution time of validation logic. Using `ctx.at` would make the handlers deterministic and consistent.

---

### S-4 — `git_ops.py` primitives catch `Exception` and return empty string without logging

**File:** `teleclaude/core/next_machine/git_ops.py:31-59`

`get_head_commit`, `get_ref_commit`, and `get_remote_branch_head` all catch `(GitCommandError, Exception)` and return `""` with no logging. Callers handle the empty return, but the root cause (permissions, corrupt repo, disk full) is completely lost. I-9 added logging at the handler level but the primitives themselves swallow the original exception. Adding `logger.debug` at the catch point would aid diagnostics without changing behavior.

---

## Lane Coverage

| Lane       | Status   | Notes                                                               |
| ---------- | -------- | ------------------------------------------------------------------- |
| scope      | skipped  | ad-hoc review                                                       |
| code       | executed | ctx.cwd bug (R4), backward guard (I-11), grounding invariant (I-12) |
| paradigm   | executed | fix follows established \_on_enter_finalize_ready pattern           |
| principles | executed | principle-violation-hunt — R4, I-11, I-12 found                     |
| security   | executed | no secrets, no injection found                                      |
| tests      | executed | missing direct coverage for review handlers -> I-10                 |
| errors     | executed | grounding valid-without-sha (I-12), git_ops silent failures (S-4)   |
| types      | executed | no new type issues                                                  |
| comments   | executed | R4 fix includes explanatory comment                                 |
| logging    | executed | I-9 fix verified; git_ops logging gap noted (S-4)                   |
| demo       | skipped  | ad-hoc review                                                       |
| docs       | executed | CLI surface updated correctly; removed commands confirmed gone      |
| simplify   | skipped  | REQUEST CHANGES verdict; simplify deferred                          |

---

## Fixes Applied

| Finding | Fix                                                                                                                                                      | Commit          |
| ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------- |
| C-1     | Removed `mark_phase("finalize_ready")` from `prepare.py` container path; removed unused import; updated test assertion to match `SPLIT FINALIZE:` prefix | 5510fbc32       |
| C-2     | Removed `phase`/`status` sub-checks inside `if target:` block — target now takes unconditional precedence                                                | 5510fbc32       |
| C-3     | Added `added_files = [f for f in added_files if f in session_files]` inside `if not all_files:` block                                                    | 5510fbc32       |
| I-1     | Added finalize_ready (5 guard + happy path) and finalize_handoff (guard + happy path) tests to `test_state_io.py` and `test_work_lifecycle.py`           | 7e5468ed4       |
| I-2     | Added `stamp_verdict` tests (valid, invalid phase, invalid verdict) to `test_state_io.py`                                                                | 7e5468ed4       |
| I-3     | Added `target=` API path tests to `test_todo_routes.py` (happy path, 409, 404, 400, uncommitted guard)                                                   | ae0e88b75       |
| I-4     | Added error-path tests for `_on_enter_prepared` (missing dir, missing requirements.md, missing plan)                                                     | 7e5468ed4       |
| I-5     | Removed dead idempotency checks; added comment documenting engine-level no-op semantics                                                                  | 5510fbc32       |
| I-6     | Added `all_files_true_transfers_without_session_scoping` test to `test_todo_from_main.py`                                                                | 7e5468ed4       |
| I-7     | Wrapped `_auto_commit_state` calls in try/except; returns PARTIAL response on commit failure with error log                                              | 5510fbc32       |
| I-8     | Wrapped legacy `mark_phase` call with `ValueError -> 409`; wrapped `_auto_commit_state` with commit-failure handler                                      | 5510fbc32       |
| I-9     | Added `logger.warning(...)` when `get_head_commit` returns empty in both review handlers                                                                 | 5510fbc32       |
| R4      | Review handlers now use `worktree_cwd` for `get_head_commit` and `_extract_finding_ids` instead of `ctx.cwd`                                             | _(this review)_ |
| I-10    | Added 6 direct unit tests for `_on_enter_review_changes` and `_on_enter_review_approved` (happy path, empty HEAD, non-int round, merge, dedup)           | d79d51c06       |
| I-11    | Added backward-transition guard in `_on_enter_finalize_ready`: raises ValueError when `finalize.status == "handed_off"`                                  | 7e9db1ee2       |
| I-12    | `_on_enter_prepared` now raises ValueError when `git rev-parse HEAD` fails (rc!=0 or empty SHA) instead of marking grounding valid                       | 7e9db1ee2       |

Suggestions S-1, S-2, S-3, S-4 not addressed (optional).

## Verdict

**Unresolved Critical:** 0
**Unresolved Important:** 0

**VERDICT: REQUEST CHANGES**
