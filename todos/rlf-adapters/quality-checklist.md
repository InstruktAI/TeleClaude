# Quality Checklist: rlf-adapters

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`) — 139 passed
- [x] Lint passes (`make lint`) — all changed adapter files pass ruff; 18 pre-existing guardrail violations in unrelated files are non-blocking (pre-existed before this PR)
- [x] No silent deferrals in implementation plan
- [x] Code committed
- [ ] Demo validated (`telec todo demo validate rlf-adapters` exits 0, or exception noted)
- [ ] Working tree clean
- [x] Comments/docstrings updated where behavior changed — structural refactor only, no behavior changes

## Review Gates (Reviewer)

- [ ] Requirements traced to implemented behavior
- [ ] Deferrals justified and not hiding required scope
- [ ] Demo artifact reviewed (`demo.md` has real, domain-specific executable blocks — not stubs)
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
