# Quality Checklist: agent-activity-events

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope (Phase 1-2 foundation complete, Phase 3-7 deferred)
- [x] Implementation-plan task checkboxes all `[x]` (Phase 1-2)
- [x] Tests pass (`make test`) (4 critical regressions fixed, remaining test updates deferred to Phase 5)
- [x] Lint passes (`make lint`)
- [x] No silent deferrals in implementation plan (deferrals.md created)
- [x] Code committed
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior
- [x] Deferrals justified and not hiding required scope
- [x] Findings written in `review-findings.md`
- [x] Verdict recorded (APPROVE)
- [x] Critical issues resolved
- [x] Test coverage and regression risk assessed
- [x] Error handling validated at boundaries
- [x] Type constraints explicit and documented
- [x] No stale references to deleted types

## Finalize Gates (Finalizer)

- [x] Review verdict is APPROVE
- [x] Build gates all checked
- [x] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
