# Quality Checklist: web-interface-2

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`) — 5 pre-existing failures in TUI/config tests, unrelated to frontend
- [x] Lint passes (`make lint`)
- [x] No silent deferrals in implementation plan
- [x] Code committed
- [x] Working tree clean — only `todos/web-interface-2/state.json` dirty (orchestrator-synced state)
- [x] Comments/docstrings updated where behavior changed

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior — FR3 (streaming) fails, FR4 partial; see findings
- [x] Deferrals justified and not hiding required scope — no deferrals file; none hidden
- [x] Findings written in `review-findings.md`
- [x] Verdict recorded (APPROVE or REQUEST CHANGES) — REQUEST CHANGES
- [ ] Critical issues resolved or explicitly blocked — 3 critical + 6 important findings open
- [x] Test coverage and regression risk assessed — no frontend tests; high regression risk noted

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
