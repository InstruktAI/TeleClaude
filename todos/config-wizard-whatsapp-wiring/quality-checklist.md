# Quality Checklist: config-wizard-whatsapp-wiring

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
- [x] Demo validated (`telec todo demo validate config-wizard-whatsapp-wiring` exits 0, or exception noted)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

Build verification notes:

- `make test`: PASS (`2286 passed, 106 skipped`).
- `make lint`: PASS (ruff, pyright, markdown/resource guardrails).
- `telec config validate | grep -i whatsapp`: PASS (all 7 WhatsApp env vars reported when unset).
- Interactive TUI manual walkthrough is not runnable in this non-interactive build environment; verified render wiring via unit/component tests and direct component instantiation, and captured user-flow in `demo.md`.
- Remaining working tree drift is non-build scope: orchestrator-managed `todos/config-wizard-whatsapp-wiring/state.yaml` and pre-existing untracked `.teleclaude/`.

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
