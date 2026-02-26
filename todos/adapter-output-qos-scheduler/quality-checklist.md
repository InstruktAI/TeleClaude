# Quality Checklist: adapter-output-qos-scheduler

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [ ] Requirements implemented according to scope
- [ ] Implementation-plan task checkboxes all `[x]`
- [ ] PTB rate-limiter integration is active and verified in runtime logs
- [ ] Scheduler applies to both Telegram output paths (legacy + threaded)
- [ ] Final updates are not starved by normal updates
- [ ] Dynamic cadence math is covered by tests
- [ ] Fairness and coalescing behavior validated under multi-session load
- [ ] Tests pass (`make test` or targeted suite with rationale)
- [ ] Lint passes (`make lint`)
- [ ] No silent deferrals in implementation plan
- [ ] Runtime smoke checks completed (`make restart`, `make status`, relevant log grep)
- [ ] Working tree clean
- [ ] Comments/docstrings updated where behavior changed
- [ ] Docs updated for tuning knobs and behavior

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior (FR1-FR9 verified; FR4 partial — `min_session_tick_s` inert, see finding #1)
- [x] Rate-limit claims and formulas match source evidence (`effective_output_mpm` and `global_tick_s` match FR4; `target_session_tick_s` not implemented)
- [x] Coalescing design does not introduce stale/final-output regressions (latest-only + priority FIFO verified)
- [x] Queueing does not block unrelated adapter lanes (async background task; enqueue is non-blocking)
- [x] Deferrals justified and not hiding required scope (5.2/5.3 require live daemon; documented)
- [x] Findings written in `review-findings.md` (3 Important, 3 Suggestions)
- [x] Verdict recorded: **APPROVE**
- [x] No critical issues found

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.yaml`
- [ ] Roadmap updated (if prioritization changed)
- [ ] Todo/worktree cleanup complete
