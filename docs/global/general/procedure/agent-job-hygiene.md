---
description: 'Standard guardrails for agent-type jobs: structured output, fix-forward, clean shutdown, auditability.'
visibility: 'public'
---

# Agent Job Hygiene — Procedure

## Goal

Ensure every agent job produces auditable output, fixes forward when possible, stays
within scope, and shuts down cleanly. This procedure applies to all agent-type jobs
across all projects.

## Preconditions

- The agent was started by the job runner with full tool access and one value: the
  job's identity, which is the snippet ID of the procedure its declaration points at.
- The agent has loaded that procedure with its required-read closure
  (`telec docs get <id> --closure`) — the only source of task instructions.

## Steps

### 1. Read your procedure, nothing else

Your job procedure is your complete scope. Do not invent work beyond what it describes.
The closure has already delivered every document it depends on. Otherwise, stay in lane.

### 2. Do the work

Execute the task the procedure describes. Run the scripts and tools it tells you
to use. You are the supervisor — the scripts are the workers.

### 3. Fix forward

If a script fails, do not just log and move on. You own the outcome.

- **Diagnose**: read the error, understand what went wrong.
- **Fix if in scope**: if the issue is in your job's own scripts or data, fix it and
  re-run. Your scope is the files the procedure names — nothing beyond.
- **Record if out of scope**: if the issue is in unrelated code or infrastructure,
  record it in the run report and move on. Do not chase it.
- **Limit**: one fix attempt per failure. If the fix doesn't resolve it, record
  the failure with both the original error and what you tried.

### 4. Write a run report

<!-- planned-change:generic-job-declarative-model -->
When done, write a report to `~/.teleclaude/jobs/{job_id}/runs/{YYMMDD-HHMMSS}.md`,
where `{job_id}` is the identity you were started with. Create the directory if it
doesn't exist.
<!-- change:generic-job-declarative-model -->
When done, write a report to
`~/.teleclaude/jobs/{project_slug}/{job_id}/runs/{YYMMDD-HHMMSS}.md`, where `{job_id}` is the
identity you were started with and `{project_slug}` is the project you were started in. Create
the directory if it doesn't exist.
<!-- /planned-change:generic-job-declarative-model -->

Report format:

```markdown
# {job_id} — {YYYY-MM-DD}

## Summary

1-3 sentences describing what happened.

## Actions

- Action taken and result
- Action taken and result

## Fixes

- Fix applied and outcome, or "None"

## Errors

- Unresolved error description, or "None"
```

If the procedure defines additional output fields (metrics, counts, links), include
them after Errors.

The markdown report above is the human-readable audit. Additionally, close the run by
reporting a structured outcome to the runner:

`telec jobs report {job_id} --success true|false --message "<1-line summary>" [--items-processed <n>] [--error <text> ...]`

This structured call is the single channel through which the runner learns the run's real
outcome and closes it; a run that is never reported is detected as a stall. Report
`--success true` only when the work actually completed, `--success false` with the error
summary otherwise. Do not emit events or publish to channels directly — `telec jobs report`
is the only outcome channel.

### 5. Stop

You are done. Do not explore the codebase. Do not save memories (jobs are transactional,
not relational). Do not start bonus work. Go idle immediately.

Avoid these anti-patterns:

- **Scope creep**: touching code outside the files the procedure names.
- **Memory saves**: job agents must not call the Memory API to save observations.
  Jobs produce reports, not relationship context.
- **Infinite retry**: one fix attempt per failure. If it doesn't work, record and continue.
- **Missing report**: every run must produce a report, even if the job had nothing to do.
  A "nothing to process" report is valid and expected.
- **Gold-plating**: fixing something that works but "could be better." Only fix what breaks.

## Outputs

<!-- planned-change:generic-job-declarative-model -->
- A run report at `~/.teleclaude/jobs/{job_id}/runs/{YYMMDD-HHMMSS}.md`.
<!-- change:generic-job-declarative-model -->
- A run report at `~/.teleclaude/jobs/{project_slug}/{job_id}/runs/{YYMMDD-HHMMSS}.md`.
<!-- /planned-change:generic-job-declarative-model -->

- A structured run outcome reported via `telec jobs report` that closes the run.

- Whatever artifacts the procedure defines (ideas files, CSV updates, etc.).
- Any fixes committed to the job's own scripts (within the procedure's scope only).

## Recovery

- If the run report directory does not exist, create it before writing. Never skip the report.
- If the procedure cannot be loaded, write an error report and stop — do not invent scope.
- If a tool call produces an unexpected error outside the job's scope, record it in the Errors section and continue. Do not chase unrelated failures.
