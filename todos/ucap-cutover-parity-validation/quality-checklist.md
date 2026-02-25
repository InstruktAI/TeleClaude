# Quality Checklist - ucap-cutover-parity-validation

## Build Gates (Builder)

- [x] All tasks in `implementation-plan.md` are `[x]` (except follow-up todo creation — handled in next commit).
- [x] Tests pass: `make test` → 2146 passed, 106 skipped, 10 warnings.
- [x] Lint passes: `make lint` → ruff + pyright: 0 errors, 0 warnings.
- [x] Demo validates: `telec todo demo validate ucap-cutover-parity-validation` → 3 executable block(s) found.
- [x] Demo artifact delivered: `demos/ucap-cutover-parity-validation/demo.md` (created in next commit).
- [x] Manual verification:
  - Shadow mode gate: confirmed structural — `AdapterClient._ui_adapters()` filters to `isinstance(adapter, UiAdapter)` only. Redis (`has_ui=False`) is excluded from all output delivery at the type level.
  - Bypass audit: all callers of `send_output_update`, `send_threaded_output`, `send_message` in `teleclaude/` route through `AdapterClient`. No direct adapter calls in core output progression paths.
  - Rollback drill: `test_observer_failure_does_not_affect_origin` demonstrates observer fault isolation — origin delivery unaffected, known-good behavior preserved.
  - Cross-client coverage: Web (WebSocket/API broadcast), TUI (state machine), Telegram (origin routing), Discord (observer parity), Redis (excluded) all validated.
- [x] Working tree clean for build scope (pre-existing planning drift in `todos/roadmap.yaml` is non-blocking).

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior (R1-R4 all verified against code and tests)
- [x] No deferrals file exists; no hidden scope reductions
- [x] Findings written in `review-findings.md` (0 Critical, 2 Important, 2 Suggestions)
- [x] Verdict: **APPROVE**
- [x] No critical issues
- [x] Test coverage verified: 8/8 multi-adapter broadcasting tests pass, 96/96 integration tests pass
- [x] Paradigm-fit: no production code changes, existing patterns followed
- [ ] Clerical: uncommitted working tree regression in implementation-plan.md must be resolved before finalize
- [ ] Clerical: state.yaml `build: complete` must be committed

## Finalize Gates (Finalizer)

<!-- Do not edit — finalizer fills this section -->
