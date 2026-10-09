---
description: 'The telec code runner (test/lint/format, via make) launches its native toolchain as a detached process-group leader and reaps the whole group before returning — on a caught signal, a propagating exception, and the normal-return path — so no suite-spawned descendant survives reparented to PID 1.'
visibility: 'public'
---

# Quality Runner Process Groups — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

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

#### UC-CQD2: telec code lint runs a guardrails step under the bundled interpreter regardless of the launching interpreter

```gherkin
Given telec code lint is launched by an interpreter that lacks TeleClaude's runtime dependencies
When the guardrails lane runs a step that imports teleclaude
Then the step's subprocess runs under the bundled TeleClaude checkout's venv interpreter
And the step does not fail with ModuleNotFoundError for a TeleClaude runtime dependency
```

#### UC-CQD3: routine lint does not execute CLI help paths

```gherkin
Given an agent invokes routine or repository-wide lint
When the guardrails lane runs
Then it does not start CLI commands solely to validate their help behavior
```

#### UC-CQD4: Guardrail stage durations distinguish subprocess checks from source validation

```gherkin
Given a quality gate runs the guardrail lane
When a stage returns or raises an exception
Then a completion record names the stage, outcome, monotonic elapsed milliseconds, execution root, process id, and lane-run id
And successful completion is logged at DEBUG and unsuccessful completion at ERROR
And stage entry is available at TRACE, including in-process source validation
And the original return or exception still determines the gate outcome
And records are emitted per stage rather than per candidate file
```

## Known caveats

- Abrupt process termination can prevent a stage's completion record. TRACE
  entry records identify which stage was entered when diagnosing that case.
- Guardrail stage durations do not include earlier hook startup or Git-tree
  materialization, and do not time the separate native toolchain.

## See also

- docs/local/adr/0064-runner-reaps-process-group-on-normal-exit.md
- docs/local/adr/0050-restore-declarative-test-budgets.md
- docs/global/general/spec/tools/telec-cli.md
