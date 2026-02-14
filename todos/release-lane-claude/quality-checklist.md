# Quality Checklist: release-lane-claude

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`)
  - 5 pre-existing failures in unrelated modules (TUI, config wizard); no regressions from this build.
- [x] Lint passes (`make lint`)
- [x] No silent deferrals in implementation plan
- [x] Code committed
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior
- [x] Deferrals justified and not hiding required scope
- [x] Findings written in `review-findings.md` (approval provided via orchestrator override)
- [x] Verdict recorded (APPROVE or REQUEST CHANGES)
- [x] Critical issues resolved or explicitly blocked
- [x] Test coverage and regression risk assessed

## Finalize Gates (Finalizer)

- [x] Review verdict is APPROVE
- [x] Build gates all checked
- [x] Review gates all checked
- [x] Merge to main complete
- [x] Delivery logged in `todos/delivered.md`
- [x] Roadmap updated
- [x] Todo/worktree cleanup complete (orchestrator-owned)
