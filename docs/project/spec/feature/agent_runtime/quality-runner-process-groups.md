---
description: 'The telec code runner (test/lint/format, via make) launches its native toolchain as a detached process-group leader and reaps the whole group before returning — on a caught signal, a propagating exception, and the normal-return path — so no suite-spawned descendant survives reparented to PID 1.'
visibility: 'public'
---

# Quality Runner Process Groups — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

`telec code test`, `telec code lint`, and `telec code format` all invoke their
native `make` target through the same runner primitive
(`_run_in_process_group` in `teleclaude/cli/telec/handlers/quality.py`), which
launches the target as its own session/process-group leader
(`start_new_session=True`). Detachment means the runner — not the caller's
terminal — owns reaping the group: before the runner returns the child's exit
code, it tears down the whole process group on every return path, not only
the abnormal ones, so a descendant the target spawned (`make` → `bash` →
`pytest` → `execnet` workers) never survives reparented to PID 1.

## Canonical fields

### Use cases

#### UC-CQD1: telec code test reaps a suite-spawned descendant on a normal-exit (session_timeout) interrupt

```gherkin
Given telec code test runs the suite as a detached session/process-group leader
And a suite-spawned OS descendant outlives pytest
When pytest returns normally with no signal to the runner (an xdist session_timeout interrupt, exit code 2)
Then the runner reaps the child process group before returning the exit code
And no suite-spawned descendant survives reparented to PID 1
```

## See also

- docs/project/adr/0064-runner-reaps-process-group-on-normal-exit.md
- docs/project/adr/0050-restore-declarative-test-budgets.md
- docs/global/general/spec/tools/telec-cli.md
