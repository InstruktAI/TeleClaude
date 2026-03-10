# Quality Checklist: mirror-runtime-isolation

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
- [x] Demo validated (`telec todo demo validate mirror-runtime-isolation` exits 0, or exception noted)
- [ ] Working tree clean
- [x] Comments/docstrings updated where behavior changed

### Build Verification Notes

- Targeted mirror-suite verification: `uv run pytest -n 0 tests/unit/test_transcript_discovery.py tests/unit/test_mirror_worker.py tests/unit/test_mirror_generator.py tests/unit/test_mirror_processors.py tests/unit/test_mirror_store.py tests/unit/test_mirror_prune_migration.py tests/unit/test_history_mirror_search.py tests/unit/test_mirror_api_routes.py` passed (`29 passed`). `uv run pytest -n 0 tests/unit/test_mirror_prune_migration.py` passed again after setting `db.row_factory` in migration `027`.
- Full repo verification: `make test` passed (`3401 passed, 5 skipped, 1 xpassed`). `make lint` passed after guardrails, markdown/resource validation, ruff, pyright, and report-only pylint baseline output. `make status` reported daemon and API healthy.
- Demo validation: `telec todo demo validate mirror-runtime-isolation` passed (`2 executable block(s) found`).
- Manual verification: Direct-send API regression was traced before changing anything. The stale test duplicated the `unregister_listener` patch and asserted on the wrong mock; the route behavior itself already matched the intended path. Verified by reproducing the failure, fixing the duplicate patch, rerunning the targeted test, then rerunning `make test`.

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
