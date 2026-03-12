# Plan Review Findings: prepare-pipeline-hardening

## Critical

### C1: The plan still fails DOR Gate 2 because it combines multiple independently shippable workstreams

The current plan bundles at least four distinct delivery streams into one build
session:

- prepare-core schema/lifecycle/review-routing changes in `core.py`
  and the new helper module (Tasks 1-6, 10-11)
- split inheritance in `teleclaude/todo_scaffold.py` (Task 7)
- CLI/API/session-launch surface changes for `--additional-context`
  (Task 12)
- documentation/demo/event-surface updates across the docs tree
  and CLI help text (Tasks 8-9, 13)

Those streams touch different subsystems, have different verification lanes,
and are independently valuable. For example, split inheritance can ship without
the session-launch `--additional-context` chain, and the CLI/API flag can ship
without changing `split_todo()`. The plan therefore exceeds a single builder
session and should be split into dependent todos before implementation starts.
