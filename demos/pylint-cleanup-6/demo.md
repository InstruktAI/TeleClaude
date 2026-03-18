# Demo: pylint-cleanup-6

## Validation

```bash
pylint \
  teleclaude/core/db \
  teleclaude/core/integration \
  teleclaude/core/tmux_bridge \
  teleclaude/core/command_handlers \
  teleclaude/core/adapter_client \
  teleclaude/core/models \
  teleclaude/core/agent_coordinator \
  teleclaude/core/operations \
  teleclaude/core/migrations
```

## Guided Presentation

Run the scoped `pylint` command above and verify it exits cleanly with no violations.

This delivery is limited to lint cleanup in the assigned core directories. The repo-wide `make test`
and `make lint` gates still surface unrelated failures outside this slug's scope; those are recorded
in `todos/pylint-cleanup-6/deferrals.md`.
