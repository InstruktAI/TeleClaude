# Quality Checklist: conversation-projection-unification

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`)
- [ ] Lint passes (`make lint`)
- [x] No silent deferrals in implementation plan
- [x] Code committed
- [x] Demo validated (`telec todo demo validate conversation-projection-unification` exits 0, or exception noted)
- [x] Working tree clean (excluding approved orchestrator drift)
- [x] Comments/docstrings updated where behavior changed

### Build Notes

- Focused regression verification passed on March 7, 2026 via `pytest -n 0 tests/unit/test_output_projection.py tests/unit/test_transcript_converter.py tests/unit/test_threaded_output_updates.py tests/unit/test_polling_coordinator.py tests/unit/test_api_server.py -q` (`215 passed`).
- Full test verification passed on March 7, 2026 via `make test` (`3252 passed, 5 skipped`) after stabilizing the multi-adapter SQLite test fixtures and hardening concurrent `state.yaml` reads.
- Demo validation passed on March 7, 2026 via `telec todo demo validate conversation-projection-unification`.
- `make lint` is blocked by repository-wide `pylint teleclaude` findings outside this todo's scope. Guardrails, markdown/resource validation, ruff, and pyright all passed on current HEAD before pylint failed.
- Post-commit `git status --short` is expected to contain only approved orchestrator drift: `.teleclaude/worktree-prep-state.json`, `todos/conversation-projection-unification/state.yaml`, and `todos/roadmap.yaml`.
- Manual UI verification was not run in this worktree; observable parity is covered by the new automated projection and API regression tests.

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
