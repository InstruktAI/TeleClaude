# Quality Checklist: agent-availability-enforcement-migration

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
- [x] Demo validated (`telec todo demo validate agent-availability-enforcement-migration` exits 0, or exception noted)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

Build verification notes:

- `make test`: PASS (`2255 passed, 106 skipped`)
- `make lint`: PASS (`ruff`, `pyright`, guardrails)
- `telec todo demo validate agent-availability-enforcement-migration`: PASS (`6 executable block(s)`)
- `instrukt-ai-logs teleclaude --since 15m --grep "agent routing|availability|rejected"`: executed successfully (exit 0)
- Working tree cleanliness validated for build scope; remaining dirty file `todos/agent-availability-enforcement-migration/state.yaml` is orchestrator-managed drift and intentionally uncommitted

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
