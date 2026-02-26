# Quality Checklist: agent-config-driven-selection-contract

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
- [x] Demo validated (`telec todo demo agent-config-driven-selection-contract` exits 0, or exception noted)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

Manual verification:

- `telec todo demo validate agent-config-driven-selection-contract` -> `Validation passed: 5 executable block(s) found`.
- `uv run pytest -q tests/unit/cli/test_tool_commands.py::test_handle_sessions_run_omits_agent_when_not_provided tests/unit/cli/test_tool_commands.py::test_handle_sessions_run_includes_explicit_agent` -> `2 passed`.

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
