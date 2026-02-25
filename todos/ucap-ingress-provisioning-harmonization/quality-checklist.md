# Quality Checklist: ucap-ingress-provisioning-harmonization

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [ ] Requirements implemented according to scope
- [ ] Implementation-plan task checkboxes all `[x]`
- [ ] Tests pass (`make test`)
- [ ] Lint passes (`make lint`)
- [ ] No silent deferrals in implementation plan
- [ ] Code committed
- [ ] Demo validated (`telec todo demo validate ucap-ingress-provisioning-harmonization` exits 0, or exception noted)
- [ ] Working tree clean
- [ ] Comments/docstrings updated where behavior changed

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior — R1–R5 all verified; code fixes correct
- [x] Deferrals justified and not hiding required scope — no deferrals.md exists
- [x] Findings written in `review-findings.md`
- [x] Verdict recorded (APPROVE or REQUEST CHANGES) — REQUEST CHANGES (round 2)
- [x] Critical issues resolved or explicitly blocked — no critical issues; 1 Important: documentation state regression
- [x] Test coverage and regression risk assessed — 2132 passed, R1–R5 all covered, no regression risk from fixes

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
