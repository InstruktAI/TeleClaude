# Quality Checklist: refactor-agent-readiness

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
- [x] Demo validated (`telec todo demo validate refactor-agent-readiness` exits 0, or exception noted)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

### Build Notes

- Targeted verification: `pytest tests/unit/core/test_agent_readiness.py tests/unit/core/test_agents.py tests/unit/core/test_events.py tests/unit/test_daemon_session.py -q`
- Full gates: `make lint`, `make test`, and `telec todo demo validate refactor-agent-readiness` all passed.
- Boundary checks: verified `teleclaude/daemon_session.py` imports `wait_for_agent_ready`, no longer defines `AGENT_PROMPT_READY_MARKERS`, and no longer defines `_wait_for_agent_prompt_ready`.
- Manual verification gap: this was an internal daemon/core refactor, so observability was validated via automated tests and demo blocks rather than a separate live UI walkthrough.

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
