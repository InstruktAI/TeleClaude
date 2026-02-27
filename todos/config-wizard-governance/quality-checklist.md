# Quality Checklist: config-wizard-governance

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
- [x] Demo validated (`telec todo demo validate config-wizard-governance` exits 0, or exception noted)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

Manual verification notes:

- Verified governance text is present in all four target docs via direct file reads for SC-1 through SC-4.
- Verified frontmatter delimiter integrity (`---`) for all four edited snippets (SC-6).
- `make test` passed: 2237 passed, 106 skipped.
- `make lint` passed: 0 errors, 0 warnings.
- `telec sync` passed with no errors on this todo's docs.
- `telec todo demo validate config-wizard-governance` passed: 6 executable block(s) found.
- `git status` cleanliness: only orchestrator-managed drift remains (`todos/config-wizard-governance/state.yaml`, `todos/roadmap.yaml`).

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
