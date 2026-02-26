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

Manual verification notes:

- Replaced flaky cross-repo same-slug test with a deterministic lock-scope invariant test over `_get_slug_single_flight_lock`.
- Verified targeted lock-scope test stability with 40 consecutive passes.
- Verified full quality gates with `make lint` (pass) and `make test` (`2208 passed, 106 skipped, 1 warning`).
- Verified demo structure with `telec todo demo validate api-todos-work-stability-hardening --project-root .` (3 executable blocks).
- Attempted runtime operational validation (`telec todo work ...` twice + `instrukt-ai-logs ... --grep NEXT_WORK_PHASE`), but worker role permissions block `telec todo work`; no runtime logs were emitted from this session.

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
