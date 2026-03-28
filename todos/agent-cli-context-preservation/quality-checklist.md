# Quality Checklist: agent-cli-context-preservation

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
- [x] Demo validated (`telec todo demo validate agent-cli-context-preservation` exits 0, or exception noted)
- [x] User-facing verification evidence recorded
- [x] Browser-based frontend or web UI changes smoke-tested with Playwright
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

Verification evidence:

- `make lint` passed in the normal agent session after the doc-reference normalization and `tools/lint.sh` top-level-import gate alignment. Resource validation emitted 170 warnings but exited successfully.
- `make test` passed with session-scoped coverage of the touched install, distribute, and init-flow tests.
- `telec todo demo validate agent-cli-context-preservation` passed with 8 executable bash blocks.
- CLI/file verification confirmed `bin/init/setup_agent_hooks.sh` is absent, `bin/init/configure_agent_cli.py` exists, and repo-local prototype files `.codex/config.toml` / `.codex/CODEX.compaction.md` are absent.
- Playwright smoke test is not applicable because this delivery does not change browser-based UI behavior.

## Review Gates (Reviewer)

- [x] Requirements traced to implemented behavior
- [x] Deferrals justified and not hiding required scope
- [x] Demo artifact reviewed (`demo.md` has real, domain-specific executable blocks — not stubs)
- [x] Findings written in `review-findings.md`
- [x] Verdict recorded (APPROVE or REQUEST CHANGES)
- [x] Critical issues resolved or explicitly blocked
- [x] Test coverage and regression risk assessed
- [x] User-facing verification evidence reviewed
- [x] Browser-based frontend or web UI changes verified with Playwright during review, or gap recorded as a finding

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
