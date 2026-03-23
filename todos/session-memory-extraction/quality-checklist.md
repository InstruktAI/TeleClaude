# Quality Checklist: session-memory-extraction

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
- [x] Demo validated (`telec todo demo validate session-memory-extraction` exits 0, or exception noted)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

### Builder Notes

- Verified `pytest tests/unit/jobs/test_session_memory_extraction.py -q`: 17 passed.
- Verified `pytest tests/unit/services/test_maintenance_service.py -q -k idle_compaction`: 1 passed.
- Verified `make test`: 4253 passed.
- Verified `make lint`: passed after removing two stale `type: ignore` comments from the new spec coverage.
- Verified `telec todo demo validate session-memory-extraction`: passed with 4 executable blocks.
- Verified `rg -n "/compact|send_keys_existing_tmux" jobs/session_memory_extraction.py` returned no matches, confirming the dead tmux injection path is gone.

## Review Gates (Reviewer)

- [ ] Requirements traced to implemented behavior
- [ ] Deferrals justified and not hiding required scope
- [ ] Demo artifact reviewed (`demo.md` has real, domain-specific executable blocks — not stubs)
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
