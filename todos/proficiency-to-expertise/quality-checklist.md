# Quality Checklist: proficiency-to-expertise

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test` — 3229 passed; 6 pre-existing failures unrelated to expertise scope; all 86 expertise-related tests pass)
- [x] Lint passes (`make lint` — 1 pre-existing pyright error in api_server.py, unrelated to expertise changes)
- [x] No silent deferrals in implementation plan (TUI sub-todo and pre-existing test failures explicitly documented as deferred)
- [x] Code committed
- [x] Demo validated (`telec todo demo validate proficiency-to-expertise` — 7 blocks found)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed (proficiency → deprecated inline comments)

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
