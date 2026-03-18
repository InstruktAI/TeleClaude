# Quality Checklist: pylint-cleanup-6

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
- [x] Code committed
- [x] Demo validated (`telec todo demo validate pylint-cleanup-6` exits 0, or exception noted)
- [ ] Working tree clean
- [x] Comments/docstrings updated where behavior changed

## Build Notes

- Scoped `pylint` passes for all paths listed in `requirements.md`.
- `make test` still fails only in out-of-scope suites: `tests/unit/install/test_git_wrapper_permissions.py` and `tests/unit/test_todo_from_main.py`.
- `make lint` still fails only in out-of-scope guardrail hits: `teleclaude/daemon_session.py`, `teleclaude/cli/session_auth.py`, `teleclaude/core/next_machine/`, and `scripts/helpers/nano_banana_helper.py`.

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
