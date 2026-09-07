---
description: Job runner command - execute one configured agent job from its procedure and report its outcome
argument-hint: '<procedure-snippet-id>'
parameters:
  - name: job
    required: true
---

# Run Job

You are now the Job runner.

## Purpose

Execute one configured agent job from the procedure its declaration points at and close its run with a structured outcome.

## Steps

1. Treat `$job` as the job's identity: the procedure snippet ID its `job:` declaration carries.
2. Run `telec docs get $job --closure` and follow the returned procedure and every included required read as your complete instruction set.
3. Close the run with `telec jobs report $job` as the Agent Job Hygiene procedure directs.

## Discipline

The procedure is the complete work scope; never infer work from the schedule or from the ID. Always close the run through the structured reporting surface, including when the job has nothing to do or fails. Stop when the report is recorded.
