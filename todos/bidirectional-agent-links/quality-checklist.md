# Quality Checklist: bidirectional-agent-links

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
- [x] Demo validates (`telec todo demo validate bidirectional-agent-links`)
- [x] Demo artifact copied to `demos/bidirectional-agent-links/demo.md`
- [x] No silent deferrals in implementation plan
- [x] Code committed
- [x] Working tree clean for build-scope changes
- [x] Comments/docstrings updated where behavior changed
- [x] Manual verification recorded

Manual verification (builder):

- Verified direct handshake create/reuse, sender-excluded fan-out, and single-party severing via `tests/unit/test_bidirectional_links.py`.
- Verified worker notification path remains operational via `tests/unit/test_session_listeners.py`, `tests/unit/test_agent_coordinator.py`, and full `make test`.
- Verified cross-computer stop payload forwarding decode path via `tests/unit/test_redis_adapter.py`.

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
