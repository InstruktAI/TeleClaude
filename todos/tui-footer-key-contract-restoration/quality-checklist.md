# Quality Checklist: tui-footer-key-contract-restoration

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
- [x] Demo validated (`telec todo demo validate tui-footer-key-contract-restoration` exits 0, or exception noted)
- [x] Working tree clean
- [x] Comments/docstrings updated where behavior changed

### Manual Verification Notes

- `SessionsView.check_action()` gating for computer/project/session nodes confirmed via unit tests.
- `PreparationView` computer grouping: `_rebuild()` now creates `ComputerHeader` → `ProjectHeader` → `TodoRow` hierarchy; verified via mock-container tests.
- `StartSessionModal` path_mode: `~` resolution via `os.path.expanduser()`, inline error on invalid path, confirmed via unit tests.
- `NewProjectModal`: duplicate name/path rejection, valid input returns `NewProjectResult`, confirmed via unit tests.
- `SessionsView._default_footer_action()` returns `"focus_pane"` for computer (Enter opens path-mode modal); `"new_session"` for project; `"focus_pane"` for session.
- Global bindings audit: `q`, `r`, `t` have `show=True` in app.py; `1/2/3/4` have `show=False`. TelecFooter Row 3 renders speech/animation as icon toggles (not standard bindings). No changes needed.
- Build environment: TUI cannot be launched without a running daemon; visual verification deferred to post-merge demo run.

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
