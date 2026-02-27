# Quality Checklist: tui-footer-key-contract-restoration

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
- [ ] Demo validated (`telec todo demo validate tui-footer-key-contract-restoration` exits 0, or exception noted)
- [ ] Working tree clean
- [ ] Comments/docstrings updated where behavior changed

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior
- [x] Deferrals justified and not hiding required scope (no deferrals.md exists)
- [x] Findings written in `review-findings.md`
- [x] Verdict recorded: APPROVE
- [x] Critical issues resolved or explicitly blocked (0 critical)
- [x] Test coverage and regression risk assessed (24 new tests, 2418 total pass)

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
