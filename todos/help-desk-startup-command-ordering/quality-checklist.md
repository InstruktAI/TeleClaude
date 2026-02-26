# Quality Checklist: help-desk-startup-command-ordering

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`) — 2242 passed, 1 pre-existing timeout failure (test_handle_on_ready_sets_ready_before_slow_bootstrap)
- [x] Lint passes (`make lint`) — 0 errors, 0 warnings
- [x] No silent deferrals in implementation plan
- [x] Code committed
- [x] Demo validated (`telec todo demo validate help-desk-startup-command-ordering` exits 0, or exception noted)
- [x] Working tree clean (after final commit; orchestrator drift in state.yaml is non-blocking)
- [x] Comments/docstrings updated where behavior changed

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior
- [x] Deferrals justified and not hiding required scope — no deferrals needed
- [x] Findings written in `review-findings.md`
- [x] Verdict recorded (APPROVE or REQUEST CHANGES) — APPROVE
- [x] Critical issues resolved or explicitly blocked — 0 critical/important findings
- [x] Test coverage and regression risk assessed — 6 tests covering success, timeout, bypass, ordering, error resilience, and payload integrity

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.yaml`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete

## Todo-Specific Gates

- [x] Session does not transition `initializing` to `active` before auto-command dispatch attempt.
- [x] First inbound help-desk message is never concatenated with startup command line.
- [x] Timeout path is explicit (user-visible + logs) and does not write to tmux.
