---
id: 'general/procedure/maintenance/log-bug-hunter'
type: 'procedure'
domain: 'software-development'
scope: 'project'
description: 'Proactive log scanning procedure that discovers errors, fixes inline or promotes to todos, and writes run reports.'
---

# Log Bug Hunter — Procedure

## Required reads

@~/.teleclaude/docs/general/procedure/agent-job-hygiene.md
@docs/project/spec/jobs/log-bug-hunter.md

## Goal

Proactively discover errors in daemon logs before they become user-visible incidents.
Fix what can be fixed inline; promote what cannot into actionable work items.

This procedure is the automated equivalent of the "check current health" step from
the maintenance cadence — run continuously so weekly passes find fewer surprises.

## Preconditions

1. The runner is executing as the `log-bug-hunter` job.
2. `instrukt-ai-logs teleclaude --since 1h` is available and returns structured log output.
3. The agent has read access to the codebase for diagnosis.
4. The agent can commit fixes to the current branch (main).
5. Previous run reports are available for deduplication at `~/.teleclaude/jobs/log-bug-hunter/runs/`.

## Steps

1. Collect logs from the last hour:
   - Run `instrukt-ai-logs teleclaude --since 1h`.
   - If no output or tool unavailable, write a "nothing to process" report and stop.

2. Extract error signals:
   - Identify lines containing errors, exceptions, tracebacks, and repeated warnings.
   - Group related log lines into distinct error instances.
   - Ignore informational and debug-level output.
   - If no error signals are found, write a "clean run" report and stop.

3. Deduplicate against previous runs:
   - Read the most recent run reports (up to 3).
   - Skip errors already reported in previous runs unless they have new context
     (different traceback, increased frequency, new trigger).
   - An error that persists across 3+ consecutive runs without a fix should be
     escalated with a `P1` classification.

4. Classify each unique error using the triage severity model:
   - **P0**: service unusable, data loss, security breach.
   - **P1**: major core-flow flakiness, persistent recurring error.
   - **P2**: annoying but service remains usable.
   - **P3**: low-impact, cosmetic, or edge-case only.

5. Process every error. For each error, decide fix or promote:
   - **Fix inline** when all are true:
     - Root cause is identifiable from the traceback and surrounding code.
     - Fix is within daemon codebase scope (Python files under `teleclaude/`).
     - Fix is small (a few lines), safe, and does not require a restart to verify.
     - Commit hooks (lint + tests) pass after the fix.
   - **Promote to todo** when any are true:
     - Fix requires architectural changes or touches multiple subsystems.
     - Root cause is unclear and needs investigation.
     - Fix requires service restart, config changes, or external coordination.
   - **Record only** when:
     - Error is transient and self-resolved (network blip, temporary resource pressure).
     - Error is already tracked by an existing todo.

6. Execute fixes:
   - Apply minimal fix.
   - Verify via commit hooks.
   - Commit with type `fix(scope): subject`.
   - Note: do not run `make restart`. If the fix requires a restart, note it in the
     run report. The next maintenance pass or checkpoint will pick it up.

7. Promote unfixable errors:
   - Check if a `todos/{slug}/` already exists for this error class.
   - If yes, skip (do not create duplicates).
   - If no, create `todos/{slug}/input.md` with:
     - error description,
     - log excerpt,
     - severity classification,
     - attempted diagnosis.
   - Add the slug to `todos/roadmap.yaml` with phase set to `pending` in its `state.yaml`.

8. Repeat steps 5–7 until every error from step 3 has been handled (fixed,
   promoted, or recorded). Do not stop while unprocessed errors remain.

9. When all errors are processed, write the run report to
   `~/.teleclaude/jobs/log-bug-hunter/runs/{YYMMDD-HHMMSS}.md` and stop.

## Outputs

- Inline fixes committed on main (when safe and small).
- New todo entries for errors requiring deeper work.
- Run report documenting all findings, actions, and skips.

## Recovery

1. If `instrukt-ai-logs` fails, write a report noting tool unavailability and stop.
2. If a fix breaks commit hooks, revert the fix, record the failure in the report,
   and promote the error to a todo instead.
3. If deduplication data is unavailable (no previous reports), treat all errors as new.
