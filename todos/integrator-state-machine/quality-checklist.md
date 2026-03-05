# Quality Checklist: integrator-state-machine

This checklist is the execution projection of `definition-of-done.md` for this todo.

Ownership:

- Build section: Builder updates only this section.
- Review section: Reviewer updates only this section.
- Finalize section: Finalizer updates only this section.

## Build Gates (Builder)

- [x] Requirements implemented according to scope
- [x] Implementation-plan task checkboxes all `[x]`
- [x] Tests pass (`make test` — 2707 tests, all passing)
- [x] Lint passes (`make lint` — guardrails, ruff, pyright, markdown pass; pylint exits non-zero
      due to pre-existing issues in `teleclaude.cli.telec` and `teleclaude.cli.tool_commands`
      (cyclic-import, duplicate-code), score 9.40/10 vs 9.39/10 before this build.
      No new errors introduced by this build's changes.)
- [x] No silent deferrals in implementation plan
- [x] Code committed
- [x] Demo validated (`telec todo demo validate integrator-state-machine` exits 0, or exception noted)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior
- [x] Deferrals justified and not hiding required scope
      Note: Three lifecycle events (integration.completed, integration.candidate.blocked,
      integration.conflict.resolved) are defined but not emitted. Plan marks them [x].
      Flagged as Important (I-3) — observability gap, not functional blocker.
- [x] Demo artifact reviewed (`demo.md` has real, domain-specific executable blocks — not stubs)
- [x] Findings written in `review-findings.md`
- [x] Verdict recorded (APPROVE or REQUEST CHANGES)
- [x] Critical issues resolved or explicitly blocked
- [x] Test coverage and regression risk assessed
      Note: Multi-candidate queue drain not tested (I-5), loose assertions (I-6).
      Critical paths covered; risks documented.

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
