---
id: 'general/procedure/agent-job-hygiene'
type: 'procedure'
scope: 'global'
description: 'Standard guardrails for agent-type jobs: structured output, fix-forward, clean shutdown, auditability.'
---

# Agent Job Hygiene — Procedure

## Goal

Ensure every agent job produces auditable output, fixes forward when possible, stays
within scope, and shuts down cleanly. This procedure applies to all agent-type jobs
across all projects.

## Preconditions

- The agent was spawned by the cron runner as a headless session.
- The agent has loaded its job spec doc (the only source of task instructions).

## Steps

### 1. Read your spec, nothing else

Your job spec doc is your complete scope. Do not invent work beyond what it describes.
If the spec references other docs, read those too. Otherwise, stay in lane.

### 2. Do the work

Execute the task described in your spec. Run the scripts and tools your spec tells you
to use. You are the supervisor — the scripts are the workers.

### 3. Fix forward

If a script fails, do not just log and move on. You own the outcome.

- **Diagnose**: read the error, understand what went wrong.
- **Fix if in scope**: if the issue is in your job's own scripts or data, fix it and
  re-run. Your scope is the files listed in your spec — nothing beyond.
- **Record if out of scope**: if the issue is in unrelated code or infrastructure,
  record it in the run report and move on. Do not chase it.
- **Limit**: one fix attempt per failure. If the fix doesn't resolve it, record
  the failure with both the original error and what you tried.

### 4. Write a run report

When done, write a report to `~/.teleclaude/jobs/{job_name}/runs/{YYMMDD-HHMMSS}.md`.
Create the directory if it doesn't exist.

Report format:

```markdown
# {job_name} — {YYYY-MM-DD}

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

If the job spec defines additional output fields (metrics, counts, links), include
them after Errors.

### 5. Stop

You are done. Do not explore the codebase. Do not save memories (jobs are transactional,
not relational). Do not start bonus work. Go idle immediately.

## Anti-patterns

- **Scope creep**: touching code outside the files listed in your spec.
- **Memory saves**: job agents must not call the Memory API to save observations.
  Jobs produce reports, not relationship context.
- **Infinite retry**: one fix attempt per failure. If it doesn't work, record and continue.
- **Missing report**: every run must produce a report, even if the job had nothing to do.
  A "nothing to process" report is valid and expected.
- **Gold-plating**: fixing something that works but "could be better." Only fix what breaks.

## Outputs

- A run report at `~/.teleclaude/jobs/{job_name}/runs/{YYMMDD-HHMMSS}.md`.
- Whatever artifacts the job spec defines (ideas files, CSV updates, etc.).
- Any fixes committed to the job's own scripts (within spec scope only).

## Recovery

- If the agent crashes mid-run, the report will be missing. The cron runner already
  logs spawn success/failure. A missing report for a spawned session indicates a crash.
- The next scheduled run starts fresh — jobs are stateless between runs.
