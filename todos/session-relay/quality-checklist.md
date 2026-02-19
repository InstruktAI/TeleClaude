# Quality Checklist: session-relay

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`) — 17/17 session-relay tests pass; 31 pre-existing failures in unrelated modules
- [x] Lint passes (`make lint`) — 0 errors, 0 warnings
- [x] No silent deferrals in implementation plan
- [x] Code committed — 3 commits (primitive, handler wiring, tests)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior — core relay primitive meets spec; handler wiring functional but has duplicate relay bug
- [x] Deferrals justified and not hiding required scope — no deferrals.md present; no silent deferrals found
- [x] Findings written in `review-findings.md` — 1 critical, 4 important, 5 suggestions
- [x] Verdict recorded (APPROVE or REQUEST CHANGES) — REQUEST CHANGES
- [ ] Critical issues resolved or explicitly blocked — 1 critical open (duplicate relay prevention)
- [x] Test coverage and regression risk assessed — relay primitive well-covered; handler wiring has zero coverage

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
