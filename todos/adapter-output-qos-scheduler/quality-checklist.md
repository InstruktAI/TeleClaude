# Quality Checklist: adapter-output-qos-scheduler

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]` (Tasks 5.2, 5.3 deferred to post-merge — see deferrals.md)
- [x] PTB rate-limiter integration active; startup logs emitted; falls back gracefully if extra missing
- [x] Scheduler applies to both Telegram output paths (send_output_update + send_threaded_output)
- [x] Final updates are not starved by normal updates (priority queue FIFO, dispatched first in both modes)
- [x] Dynamic cadence math is covered by tests (29 unit tests in test_output_qos_scheduler.py)
- [x] Fairness and coalescing behavior validated by unit tests (round-robin + coalescing tests pass)
- [x] Tests pass (`make test` — 2265 passed, 106 skipped)
- [x] Lint passes (`make lint` — 0 errors, 0 warnings)
- [x] Deferrals documented in deferrals.md (Tasks 5.2, 5.3: integration load + runtime log validation)
- [x] Runtime smoke checks deferred to post-merge (documented in deferrals.md)
- [x] Working tree clean (orchestrator drift in state.yaml/roadmap.yaml only)
- [x] Comments/docstrings updated in all modified files
- [x] Docs updated in output-polling.md (two-layer model, tuning knobs, multi-process caveat)

## Review Gates (Reviewer)

- [ ] Requirements traced to implemented behavior
- [ ] Rate-limit claims and formulas match source evidence
- [ ] Coalescing design does not introduce stale/final-output regressions
- [ ] Queueing does not block unrelated adapter lanes
- [ ] Deferrals justified and not hiding required scope
- [ ] Findings written in `review-findings.md`
- [ ] Verdict recorded (APPROVE or REQUEST CHANGES)
- [ ] Critical issues resolved or explicitly blocked

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.yaml`
- [ ] Roadmap updated (if prioritization changed)
- [ ] Todo/worktree cleanup complete
