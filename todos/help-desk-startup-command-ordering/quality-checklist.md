# Quality Checklist: help-desk-startup-command-ordering

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [ ] Requirements implemented according to scope
- [ ] Implementation-plan task checkboxes all `[x]`
- [ ] Tests pass (`make test`)
- [ ] Lint passes (`make lint`)
- [ ] No silent deferrals in implementation plan
- [ ] Code committed
- [ ] Demo validated (`telec todo demo validate help-desk-startup-command-ordering` exits 0, or exception noted)
- [ ] Working tree clean
- [ ] Comments/docstrings updated where behavior changed

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
- [ ] Delivery logged in `todos/delivered.yaml`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete

## Todo-Specific Gates

- [ ] Session does not transition `initializing` to `active` before auto-command dispatch attempt.
- [ ] First inbound help-desk message is never concatenated with startup command line.
- [ ] Timeout path is explicit (user-visible + logs) and does not write to tmux.
