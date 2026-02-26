# Quality Checklist: adapter-output-qos-scheduler

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] PTB rate-limiter integration is active and verified in runtime logs
- [x] Scheduler applies to both Telegram output paths (legacy + threaded)
- [x] Final updates are not starved by normal updates
- [x] Dynamic cadence math is covered by tests
- [x] Fairness and coalescing behavior validated under multi-session load
- [x] Tests pass (`make test` or targeted suite with rationale)
- [x] Lint passes (`make lint`)
- [x] No silent deferrals in implementation plan
- [x] Runtime smoke checks completed (`make restart`, `make status`, relevant log grep)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed
- [x] Docs updated for tuning knobs and behavior

Manual verification:

- `make restart` completed with daemon recovery and healthy API (`launchd state: running`, `/health: OK`).
- `make status` passed after restart settled (`Daemon health: HEALTHY`).
- `instrukt-ai-logs teleclaude --since 15m --grep "Output cadence summary|Rate limited|qos|scheduler"` showed live cadence summaries and rate-limit retries, including `reason=final` cadence entries during completion.
- `telec todo demo validate adapter-output-qos-scheduler` passed with `3 executable block(s) found`.

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
