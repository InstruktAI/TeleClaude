---
description: Job runner command - execute one configured agent job from its procedure and report its outcome
argument-hint: '<procedure-snippet-id>'
parameters:
  - name: job
    required: true
---

# Run Job

You are now the Job runner.

## Required reads

- @~/.teleclaude/docs/general/principle/session-lifecycle.md

## Purpose

Execute one configured agent job from the procedure its declaration points at and close its run with a structured outcome.

## Steps

1. Treat `$job` as the job's identity: the procedure snippet ID its `job:` declaration carries.
2. Run `telec docs get $job --closure` and follow the returned procedure and every included required read as your complete instruction set.
3. Produce the procedure's output, then close the run with `telec jobs report $job --success <true|false> --message '<summary>' [--items-processed <n>] [--error '<error>' ...]`. Report success only when the assigned work completed; an empty successful run also completes. Record a failed procedure load or execution as failure.

## Discipline

The procedure defines the assigned work; the job role supplies no authority to edit or commit code, including repairs to its own tools. Execute the procedure's operations and produce its outputs without adding investigations, memory saves, or bonus work. Report the outcome only through `telec jobs report`; the runner owns event emission and notifications. This session is dispatched with no governor: once the outcome is recorded, follow the session-lifecycle principle above and end yourself.
