# Review Findings: prepare-pipeline-hardening

**Reviewer:** Claude (code review)
**Branch:** `prepare-pipeline-hardening`
**Merge base:** `ded68c712c55b1b9d97d513cf4dba835e02a1ba0`
**Date:** 2026-03-12

---

## Verdict: APPROVE

All 7 Important findings resolved. 4 additional findings resolved during review. 116 tests passing.

---

## Critical

_All critical findings were resolved during review (see Resolved During Review section)._

---

## Important

### I-1: `baseline_commit` never recorded in prepare review handlers

**File:** `teleclaude/core/next_machine/core.py` (review step handlers)
**Requirement:** R17 (review efficiency — artifact diff anchor)
**Plan task:** Task 5 step 1 ("record HEAD SHA when dispatching reviewer")

The `baseline_commit` field exists in `DEFAULT_STATE` and is consumed by
`compute_artifact_diff` in `prepare_helpers.py`, but no prepare review step
handler ever writes a value to `state["baseline_commit"]`. As a result,
`compute_artifact_diff` always receives an empty `base_sha` and returns `""`,
rendering the diff anchor mechanism inert.

**Impact:** Review re-dispatches cannot provide targeted diffs to workers,
degrading the "count-and-pointer" pattern to count-only.

**Fix:** In `_prepare_step_requirements_review` and `_prepare_step_plan_review`,
record `state["baseline_commit"] = <current HEAD SHA>` before writing state, so
subsequent `compute_artifact_diff` calls have an anchor point.

---

### I-2: `additional_context` not passed in review NEEDS_WORK re-dispatch

**File:** `teleclaude/core/next_machine/core.py` (`_prepare_step_requirements_review`, `_prepare_step_plan_review`)
**Plan task:** Task 5 step 5 ("compute and pass additional_context for re-dispatch")

When a review verdict is `needs_work`, the step handlers dispatch a new worker
via `format_tool_call` but never compute or pass `additional_context`. The
`format_tool_call` function accepts the parameter, and the full CLI/API pipeline
supports it end-to-end, but the callers never supply it.

**Impact:** Re-dispatched workers receive the count-and-pointer dispatch note but
not the richer diff context that `compute_artifact_diff` + `compute_todo_folder_diff`
were designed to provide.

**Fix:** In both handlers' `needs_work` branches, call `compute_artifact_diff` and
`compute_todo_folder_diff`, compose them into an `additional_context` string, and
pass it to `format_tool_call`.

---

### I-3: `review_scoped` event registered but never emitted

**File:** `teleclaude/events/schemas/software_development.py:364`
**Requirement:** R14 (observability — prepare lifecycle events)

The `review_scoped` event schema is registered in the catalog with description
"Scoped re-review dispatched targeting specific open findings," but no code path
in `core.py` or `prepare_helpers.py` emits this event. It is a dead catalog entry.

**Impact:** Observability gap — scoped re-reviews happen but are not observable
through the event system.

**Fix:** Either emit the event in the NEEDS_WORK handler when dispatching a
re-review worker, or remove the dead registration if scoped re-review is not yet
implemented.

---

### I-4: `artifact_invalidated` event idempotency_fields/payload mismatch

**File:** `teleclaude/events/schemas/software_development.py:337` and `teleclaude/core/next_machine/core.py:3794`

Schema declares `idempotency_fields=["slug", "artifact"]` and
`meaningful_fields=["artifact"]`, but the emission payload uses key
`stale_artifacts` (a list of strings), not `artifact` (a scalar string).

The idempotency system cannot extract `artifact` from the payload, producing
broken deduplication keys.

**Fix:** Either change the payload key to `artifact` (joining the list or emitting
one event per stale artifact), or update the schema's `idempotency_fields` and
`meaningful_fields` to `stale_artifacts`.

---

### I-5: `finding_recorded` event idempotency_fields/payload mismatch

**File:** `teleclaude/events/schemas/software_development.py:348` and `teleclaude/core/next_machine/prepare_helpers.py:114-121`

Schema declares `idempotency_fields=["slug", "finding_id"]`, but the emission
payload contains `["slug", "review_type", "severity", "summary"]` — no
`finding_id` key. The `record_finding` function does not generate or include a
finding ID in the event payload.

**Fix:** Either include `finding_id` in the event payload (requires the finding
dict to carry an `id` field), or change `idempotency_fields` to match the actual
payload (e.g., `["slug", "review_type", "summary"]`).

---

### I-6: `additional_context` multiline value produces malformed CLI flag

**File:** `teleclaude/core/next_machine/core.py:318`

```python
additional_context_flag = f' --additional-context "{additional_context}"' if additional_context else ""
```

The only current caller passes multiline content (`"Missing referenced paths:\n..."`).
This produces a `telec sessions run` command line that spans multiple lines inside
double quotes. The orchestrating AI may truncate the value at the first newline or
misparse the command boundaries.

The `ADDITIONAL CONTEXT FOR WORKER` block in the template provides the same
information in a multiline-safe format, but the CLI flag is the machine-readable
channel that feeds `api_server.py`'s startup message injection.

**Fix:** Either escape newlines in the flag value (e.g., `additional_context.replace("\n", "\\n")`
with consumer-side unescape), or use `shlex.quote()` for the flag value, or remove
the flag and rely solely on the block + AI interpretation.

---

### I-7: `resolve_finding` emits false `finding_resolved` event when finding_id not found

**File:** `teleclaude/core/next_machine/prepare_helpers.py:125-146`

When `resolve_finding` is called with a `finding_id` that doesn't match any
finding in the list, the function still writes state (unchanged) and emits a
`finding_resolved` event, claiming a resolution that never happened. This
produces false positives in the event audit trail.

**Fix:** Track whether the finding was actually found. If not, skip the state
write and event emission, and log a warning:

```python
resolved = False
for f in findings:
    if isinstance(f, dict) and f.get("id") == finding_id:
        f["status"] = "resolved"
        f["resolved_at"] = now
        resolved = True
if not resolved:
    logger.warning("Finding %s not found in %s/%s", finding_id, slug, review_type)
    return
```

---

## Suggestions

### S-1: Staleness check runs on every loop iteration (redundant I/O)

**File:** `teleclaude/core/next_machine/core.py:3776-3803`

`check_artifact_staleness` runs inside the `for _iter in range(_PREPARE_LOOP_LIMIT)`
loop, calling `read_phase_state` + `artifact_digest` (disk I/O + SHA-256) on every
iteration. Combined with the existing `read_phase_state` at the loop top, this
doubles the state reads. In practice the loop runs 1-3 iterations with small files,
so performance impact is negligible, but caching or hoisting the check before the
loop would be cleaner.

---

## Resolved During Review

The following issues were found and auto-remediated during review:

### R-1: `_derive_prepare_phase` missing `needs_decision` for plan_review (was Critical)

**File:** `teleclaude/core/next_machine/core.py:3091`

The requirements_review derivation correctly checked for both `needs_work` and
`needs_decision`, but the plan_review derivation only checked `needs_work`. If
`plan_review.verdict` were `"needs_decision"` and `_derive_prepare_phase` ran as
fallback, it would incorrectly derive `GATE` instead of `PLAN_REVIEW`, potentially
advancing a blocked item past review.

**Fix applied:** Changed `plan_verdict == "needs_work"` to
`plan_verdict in ("needs_work", "needs_decision")`.

### R-2: mark-phase `--status` help text missing `needs_decision`

**File:** `teleclaude/cli/telec.py:561`

The `--status` flag description listed `approve/needs_work` as prepare verdict
values but omitted `needs_decision`, which is now a valid verdict value in
`_PREPARE_VERDICT_VALUES`.

**Fix applied:** Added `needs_decision` to the description string.

### R-3: `_run_git_prepare` fails silently with no logging

**File:** `teleclaude/core/next_machine/prepare_helpers.py:217-225`

When `_run_git_prepare` returned a non-zero exit code, the failure was invisible —
callers received an empty string with no diagnostic. Functions like
`compute_artifact_diff` that depend on git diff output would silently produce empty
results without any trace in logs.

**Fix applied:** Added `logger.warning` on non-zero return code, including the
command, return code, and stderr.

### R-4: Unused `_cascade_order` variable

**File:** `teleclaude/core/next_machine/core.py:3783`

Dead assignment that duplicated information already in `_ARTIFACT_CASCADE` and
`_phase_map`.

**Fix applied:** Removed the variable.

---

## Scope Verification

All 15 requirements (R1-R15) were traced against the diff:

| Requirement | Status |
|---|---|
| R1 (review cycle efficiency) | Implemented: count-and-pointer pattern in dispatch notes |
| R2 (structured findings in state) | Implemented: `record_finding`/`resolve_finding`, verdict routing |
| R3 (artifact lifecycle tracking) | Implemented: SHA-256 digest, `produced_at`, staleness cascade |
| R4 (ghost artifact protection) | Implemented: `_is_artifact_produced_v2` |
| R5 (needs_decision verdict) | Implemented: BLOCKED routing, `_PREPARE_VERDICT_VALUES` |
| R6 (split inheritance) | Implemented: `_inherit_parent_phase` |
| R7 (schema migration v1→v2) | Implemented: `_deep_merge_state` |
| R8 (audit stamping) | Implemented: `stamp_audit` |
| R9 (re-grounding) | Implemented: staleness check in `next_prepare` loop |
| R10 (referenced path check) | Implemented: R16 path existence in plan_drafting |
| R11 (additional_context threading) | Implemented: format_tool_call → CLI → API → worker |
| R12 (event registration) | Partially: 8 events registered, `review_scoped` never emitted (I-3) |
| R13 (demo validation) | Implemented: 7 executable blocks |
| R14 (observability) | Partial: most events wired, `baseline_commit` inert (I-1) |
| R15 (documentation) | Implemented: 9 doc files updated |

**Gold-plating check:** No unrequested features, extra CLI flags, or premature configurability detected.

## Paradigm-Fit Verification

- Data flow follows established `read_phase_state`/`write_phase_state` pattern
- Events use existing `_emit_prepare_event` fire-and-forget pattern
- New helpers extracted to `prepare_helpers.py` follow module decomposition pattern
- Split inheritance follows `todo_scaffold.py`'s existing structure
- Tests follow existing test file organization under `tests/unit/core/next_machine/`

## Security Check

- No hardcoded secrets or credentials in diff
- No PII or tokens in log statements
- Input validation present at boundaries (`isinstance` checks, empty-string guards)
- No injection vectors (subprocess calls use list form, not shell=True)
- Error messages do not expose internal paths to end users

## Test Coverage

116 tests pass. 10 new test files covering:
- Schema shape and migration
- Helper functions (digest, record, resolve, diff, input_consumed)
- Ghost artifact protection
- Review findings and verdict routing
- Audit stamping
- Staleness cascade
- Referenced path existence
- Split inheritance
- format_tool_call additional_context
- Event registration

**Gap:** No test verifies that `baseline_commit` is set before `compute_artifact_diff`
is called in the live flow (because it isn't set — see I-1).

---

## Fixes Applied

All 7 Important findings addressed in commit `fc29b0b57`.

| Finding | Fix | Commit |
|---|---|---|
| I-1 | Record HEAD SHA in `requirements_review["baseline_commit"]` and `plan_review["baseline_commit"]` before dispatching reviewer | fc29b0b57 |
| I-2 | Compute `compute_artifact_diff` + `compute_todo_folder_diff` in `needs_work` branches and pass as `additional_context` to `format_tool_call` | fc29b0b57 |
| I-3 | Emit `review_scoped` event in both `needs_work` branches when re-dispatching | fc29b0b57 |
| I-4 | Updated `artifact_invalidated` schema `idempotency_fields` and `meaningful_fields` to `stale_artifacts` to match actual payload key | fc29b0b57 |
| I-5 | Changed `finding_recorded` schema `idempotency_fields` from `["slug","finding_id"]` to `["slug","review_type","summary"]` to match actual payload | fc29b0b57 |
| I-6 | Escape newlines in `additional_context_flag` using `.replace("\n", "\\n")` before interpolating into CLI flag | fc29b0b57 |
| I-7 | Track `matched` bool in `resolve_finding`; skip write+event and log warning when `finding_id` not found | fc29b0b57 |

Tests: 116 passed. Lint: clean.
