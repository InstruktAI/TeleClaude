# Quality Checklist: daemon-independent-jobs

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test`) — unit: 1313 passed, 0 failed; integration: 67 passed,
      6 failed. The 6 integration failures are pre-existing at merge-base `01536cd4`,
      confirmed by detached-HEAD re-run (identical 6 failures). Zero integration test
      files or their exercised production code modified in this branch
      (`git diff 01536cd4..HEAD --stat -- tests/integration/` is empty).
      Failing tests: test_command_e2e (2), test_feedback_cleanup (2),
      test_e2e_smoke (1), test_mcp_tools (1) — all KeyError/AttributeError
      from missing telegram adapter mock setup unrelated to cron/agent_cli.
- [x] Lint passes (`make lint`)
- [x] No silent deferrals in implementation plan
- [x] Code committed
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

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
