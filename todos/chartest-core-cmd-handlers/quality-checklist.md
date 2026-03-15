# Quality Checklist: chartest-core-cmd-handlers

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
- [x] Demo validated (`telec todo demo validate chartest-core-cmd-handlers` exits 0, or exception noted)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

Build Notes:

- Verified `pytest tests/unit/core/command_handlers -v` passed with 34 characterization tests covering `_agent.py`, `_keys.py`, `_message.py`, `_session.py`, and `_utils.py`.
- Verified `telec todo demo validate chartest-core-cmd-handlers` passed with 2 executable demo blocks.
- Verified `make lint` passed.
- Verified `make test` passed (`794 passed`).
- Closed the flaky suite failure by fixing `tests/unit/core/next_machine/test_core.py` to patch the live `prepare_steps.compose_agent_guidance` async boundary instead of the re-export in `core.py`.
- Final `git status --short` only showed orchestrator-managed drift: `todos/chartest-core-cmd-handlers/state.yaml`.

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
