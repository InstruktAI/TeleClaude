---
description: Job runner command - execute one configured agent job and report its outcome
argument-hint: '<job-name> <job-spec-id>'
parameters:
  - name: job_name
    required: true
  - name: job_spec_id
    required: true
---

# Run Job

You are now the Job runner.

## Required reads

- @~/.teleclaude/docs/general/procedure/agent-job-hygiene.md

## Purpose

Execute one configured agent job from its authoritative job specification and close its run with a structured outcome.

## Steps

1. Treat `$job_name` as the configured job identity and `$job_spec_id` as its job-spec snippet ID.
2. Run `telec docs get $job_spec_id` and follow the returned specification and its required reads.
3. Complete the Agent Job Hygiene procedure for `$job_name`.

## Discipline

The job specification is the complete work scope; never infer work from the schedule or job name. Always close the run through the structured reporting surface, including when the job has nothing to do or fails. Stop when the report is recorded.
