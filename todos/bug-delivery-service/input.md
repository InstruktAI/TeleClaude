# Input: bug-delivery-service

Fire-and-forget bug pipeline: `telec bugs report` captures a bug, dispatches an autonomous orchestrator that fixes, reviews, and merges via PR.

## Design & Plan

- Design: `docs/plans/2026-02-22-bug-delivery-service-design.md`
- Implementation plan: `docs/plans/2026-02-22-bug-delivery-service-plan.md`

## Key Decisions

- `bug.md` file presence is the discriminator — no schema changes
- Bugs skip prepare phase (no requirements.md, no DOR gate)
- NOT roadmap items — visibility via `telec bugs list` + TUI sessions
- Per-bug branch + worktree + one orchestrator session
- Fix worker loads systematic-debugging skill
- Review uses `bug.md` as requirement source
- Done bugs deleted entirely — git is the record
- State starts at `phase: in_progress, build: pending`

## CLI

```
telec bugs report <description> [--slug <slug>]
telec bugs list
```

## Integration Points

- `teleclaude/todo_scaffold.py` — `create_bug_skeleton()`
- `teleclaude/cli/telec.py` — BUGS command enum + handlers
- `teleclaude/core/next_machine/core.py` — bug detection in `next_work()`, skip prepare, dispatch fix worker, bypass roadmap gates
- `agents/commands/next-bugs-fix.md` — fix worker command
- `agents/commands/next-review.md` — accept `bug.md` as requirement
- `templates/todos/bug.md` — bug report template
- Finalize cleanup: delete todo dir instead of archiving for bugs
