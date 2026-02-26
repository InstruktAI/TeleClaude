# Quality Checklist: api-todos-work-stability-hardening

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`)
- [x] Lint passes (`make lint`)
- [x] No silent deferrals in implementation plan
- [x] Code committed
- [x] Demo validated (`telec todo demo validate api-todos-work-stability-hardening` exits 0, or exception noted)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

Manual verification notes (2026-02-26):

- Targeted next-machine coverage: `pytest -q tests/unit/test_next_machine_worktree_prep.py tests/unit/test_next_machine_hitl.py` -> `54 passed`.
- Lint gate: `make lint` -> passed (`ruff format/check`, `pyright` clean).
- Test gate: `make test` -> `2209 passed, 106 skipped, 5 warnings`.
- Demo structure: `telec todo demo validate api-todos-work-stability-hardening --project-root .` -> `Validation passed: 3 executable block(s) found`.
- Runtime `/todos/work` verification attempt: `telec todo work api-todos-work-stability-hardening --project-root .` -> blocked by worker-role policy (`permission denied — role 'worker' is not permitted`), so direct in-session phase-log proof is not available from this worker context.

## Review Gates (Reviewer)

- [ ] Requirements traced to implemented behavior
- [ ] Deferrals justified and not hiding required scope
- [ ] Findings written in `review-findings.md`
- [ ] Verdict recorded (APPROVE or REQUEST CHANGES)
- [ ] Critical issues resolved or explicitly blocked
- [ ] Test coverage and regression risk assessed

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
