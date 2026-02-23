# Quality Checklist: discord-session-routing

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`) — 1847 passed, 3 pre-existing failures (unrelated config CLI tests)
- [x] Lint passes (`make lint`) — 0 errors, 0 warnings
- [x] No silent deferrals in implementation plan
- [x] Code committed
- [x] Demo is runnable and verified — no executable demo blocks; changes are adapter-internal
- [x] Working tree clean — only pre-existing orchestrator drift (`todos/roadmap.yaml`, `todos/discord-session-routing/state.yaml`)
- [x] Comments/docstrings updated where behavior changed

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
