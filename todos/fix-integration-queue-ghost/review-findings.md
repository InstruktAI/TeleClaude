# Review Findings: fix-integration-queue-ghost

**Review round:** 1
**Reviewer:** Claude (automated)
**Date:** 2026-03-16

---

## Scope

Lane: scope verification against `requirements.md`.

All four in-scope requirements implemented:

- Queue.json enqueue removed from daemon wiring
- Scanner accepts `handed_off` unconditionally (both `_scan_finalize_ready_candidates` and `_verify_slug_ready`)
- Tests updated for changed behavior
- Out-of-scope items preserved (`IntegrationQueue` class, `IntegrationTriggerCartridge`, `ReadinessProjection`)

One unrelated commit on the branch (`1ecf6f326` — moves `Unpack` import in `test_service.py`).
Harmless lint fix, not a scope violation.

No findings.

---

## Code

Lane: code quality and pattern review (delegated to next-code-reviewer).

TTL guard removal verified safe — the lease mechanism (`lease_store.acquire` with
`ttl_seconds=_INTEGRATION_LEASE_TTL_SECONDS`) remains intact at line 396. The removed
TTL check was a pre-filter that made freshly `handed_off` candidates invisible to all
integrator instances, not just the claiming one.

`_INTEGRATION_LEASE_TTL_SECONDS` constant retained correctly (2 references: definition
at line 44, lease usage at line 396).

`from datetime import UTC, datetime` cleanly removed — no remaining references.

`IntegrationQueue` removal scoped correctly — class and module preserved for other
consumers.

Docstrings updated to reflect new behavior.

No findings.

---

## Paradigm

Lane: paradigm-fit assessment.

- Data flow: uses established state-driven scanning, no bypasses.
- Component reuse: existing `read_phase_state`, `_run_git`, `ScannedCandidate` reused.
- Pattern consistency: simplification aligns with codebase preference for clarity.
- List comprehension in daemon callback is idiomatic Python.

No findings.

---

## Principles

Lane: principle violation hunt (design-fundamentals, fallback detection).

The change removes accidental complexity (redundant TTL guard) — KISS improvement.
No new fallback paths introduced. No DIP violations. No coupling changes.

Pre-existing `except Exception: continue` patterns in the scanner functions are not
introduced by this diff and are not counted as findings against this delivery.

No findings.

---

## Security

Lane: security review against DoD Section 5.

- No secrets in diff
- No sensitive data in logs
- No new user input paths
- No injection vectors
- Change removes code (reduces attack surface)

No findings.

---

## Tests

Lane: test coverage analysis (delegated to next-test-analyzer).

### Resolved During Review

**Finding: `_verify_slug_ready` missing test for `handed_off` status** (was Important)

The same behavioral change (TTL guard removal) was applied to both
`_scan_finalize_ready_candidates` and `_verify_slug_ready`, but only the scanner had
`handed_off` test coverage. A regression in the verifier would silently reject
`handed_off` candidates on the targeted-slug path while the scan path accepts them.

**Resolution:** Added `test_verify_handed_off_slug` to `test_auto_enqueue.py`. Test
passes and validates the verifier returns a `ScannedCandidate` for `handed_off` status.

Remaining coverage suggestions (not blocking):

- No dedicated test for daemon enqueue removal (wiring complexity; mitigated by
  integration-level tests elsewhere)
- No test for `handed_off` without `handed_off_at` field (the new code ignores
  the field entirely; low risk)
- No mixed `ready`/`handed_off` FIFO ordering test (existing FIFO test covers
  the sorting logic; status is not a sort key)

---

## Errors

Lane: silent failure hunting (delegated to next-silent-failure-hunter).

All findings are pre-existing patterns not introduced by this diff:

- `read_phase_state` bare `except Exception: continue` (step_functions.py:280-283, 332-335)
- Lease release bare `except Exception: pass` (step_functions.py:793-796)
- `_read_file_safe` returns empty on any error (step_functions.py:115-119)
- Event emission `except Exception: pass` (step_functions.py:216-217, 232-233)
- Git remote failures indistinguishable from "branch not found" (step_functions.py:301-303)

These are legitimate observability debt but are outside the scope of this bug fix.
Not counted as findings against this delivery.

No findings against this delivery.

---

## Demo

Lane: demo artifact review.

### Resolved During Review

**Finding: Demo validation block would false-fail** (was Important)

The first bash block used `grep -v "^45:"` to exclude the constant definition, but:

1. The constant is at line **44**, not 45
2. Line 396 (lease usage) is also a valid reference

The demo would `exit 1` on correct code — a false failure.

**Resolution:** Replaced with a count-based check that asserts exactly 2 references
to `INTEGRATION_LEASE_TTL_SECONDS` (definition + lease acquisition). Both
`todos/` and `demos/` copies updated.

---

## Logging

Lane: logging policy (delegated to next-code-reviewer as part of code lane).

No new logging added or removed by this diff. The removed TTL guard code had no
logging. The simplified path inherits the same (absent) logging as the `ready`
status path.

No findings.

---

## Completeness

All implementation-plan tasks checked (`[x]`). No deferrals.md present — no
deferrals to evaluate.

No findings.

---

## Why No Issues

Per zero-finding justification requirement:

1. **Paradigm-fit verified:** scanner/verifier pattern unchanged, daemon callback
   simplified to list comprehension, no new patterns introduced.
2. **Requirements validated:** each requirement traced to specific code change —
   enqueue removal in `_build_integration_trigger`, TTL guard removal in both
   scanner functions, test updates for new behavior.
3. **Duplication checked:** both `_scan_finalize_ready_candidates` and
   `_verify_slug_ready` received identical treatment — no copy-paste drift.
4. **Security reviewed:** no secrets, no injection, no auth changes, reduced
   attack surface.

---

## Verdict

**Unresolved Critical:** 0
**Unresolved Important:** 0
**Suggestions:** 3 (unrelated commit on branch, daemon test gap, minor coverage gaps)

**Verdict: APPROVE**
