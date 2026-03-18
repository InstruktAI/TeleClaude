# Quality Checklist: pylint-cleanup-2

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [ ] Tests pass (`make test`)
- [ ] Lint passes (`make lint`)
- [x] No silent deferrals in implementation plan
- [ ] Code committed
- [ ] Demo validated (`telec todo demo validate pylint-cleanup-2` exits 0, or exception noted)
- [ ] Working tree clean
- [x] Comments/docstrings updated where behavior changed

## Build Notes

- Verified assigned-scope lint with `pylint teleclaude/adapters/discord teleclaude/adapters/qos` and it passes.
- Verified assigned-scope regression coverage with `pytest tests/unit/adapters/discord tests/unit/adapters/qos` and it passes.
- `make lint` currently fails on pre-existing guardrail findings in unrelated files outside this todo's scope:
  `teleclaude/daemon_session.py`, `teleclaude/cli/session_auth.py`, `teleclaude/core/next_machine/work.py`,
  `teleclaude/core/next_machine/prepare_events.py`, `teleclaude/core/integration/state_machine.py`,
  `scripts/helpers/nano_banana_helper.py`.
- `make test` currently fails on pre-existing unrelated tests outside this todo's scope:
  `tests/unit/install/test_git_wrapper_permissions.py` and `tests/unit/test_todo_from_main.py`.
- Manual verification for this lint-only delivery consisted of rerunning the assigned-path `pylint` command and the focused adapter test suites after each fix set.

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
