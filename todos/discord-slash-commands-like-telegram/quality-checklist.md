# Quality Checklist: discord-slash-commands-like-telegram

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
- [x] Demo validated (`telec todo demo discord-slash-commands-like-telegram` exits 0, or exception noted)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed
- Manual verification: `pytest -q -n0 tests/unit/core/test_next_machine_deferral.py tests/unit/test_next_machine_demo.py tests/unit/test_diagram_extractors.py::test_extract_state_machines_regression tests/integration/test_contracts.py::test_cli_surface_contract` passed (40 passed), validating deferral dispatch messaging, demo CLI compatibility, diagram transition extraction, and CLI surface contract behavior.

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
