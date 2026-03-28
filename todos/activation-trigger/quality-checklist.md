# Quality Checklist: activation-trigger

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
- [x] Demo validated (`telec todo demo validate activation-trigger` exits 0, or exception noted)
- [x] User-facing verification evidence recorded
- [x] Browser-based frontend or web UI changes smoke-tested with Playwright
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

### Build Evidence

- Targeted activation-trigger spec suite passed: `.venv/bin/pytest tests/unit/resource_validation/test_unified_severity_spec.py tests/unit/resource_validation/test_activation_trigger_validation_spec.py tests/unit/test_activation_trigger_distribution_spec.py tests/unit/test_activation_trigger_content_spec.py -q` -> `49 passed`.
- Distribution regression passed: `.venv/bin/pytest tests/unit/test_distribute.py -q` -> `1 passed`.
- Repo gates passed: `make lint` and `make test`.
- Sync validation passed: `.venv/bin/telec sync --validate-only` exited `0`.
- User-facing CLI verification passed: `.venv/bin/telec sync` exited `0`; generated root `AGENTS.md` contains an `Activatable Procedures` section with 11 entries, includes the `telec docs get <id>` guidance, and excludes the 6 removed procedures from the baseline block.
- Skill deletion verified: `agents/skills/skill-creator` no longer exists.
- Demo validation passed: `.venv/bin/telec todo demo validate activation-trigger` found 6 executable blocks; promoted artifact to `demos/activation-trigger/demo.md`.
- Browser smoke verification not applicable: this delivery changes CLI/distribution/docs behavior only and does not modify browser-rendered UI.

## Review Gates (Reviewer)

- [ ] Requirements traced to implemented behavior
- [ ] Deferrals justified and not hiding required scope
- [ ] Demo artifact reviewed (`demo.md` has real, domain-specific executable blocks — not stubs)
- [ ] Findings written in `review-findings.md`
- [ ] Verdict recorded (APPROVE or REQUEST CHANGES)
- [ ] Critical issues resolved or explicitly blocked
- [ ] Test coverage and regression risk assessed
- [ ] User-facing verification evidence reviewed
- [ ] Browser-based frontend or web UI changes verified with Playwright during review, or gap recorded as a finding

## Finalize Gates (Finalizer)

- [ ] Review verdict is APPROVE
- [ ] Build gates all checked
- [ ] Review gates all checked
- [ ] Merge to main complete
- [ ] Delivery logged in `todos/delivered.md`
- [ ] Roadmap updated
- [ ] Todo/worktree cleanup complete
