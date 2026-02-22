---
id: 'general/procedure/maintenance/log-bug-hunter'
type: 'procedure'
domain: 'software-development'
scope: 'project'
description: 'Proactive log scanning procedure that discovers errors, fixes inline or dispatches to the bug pipeline, and writes run reports.'
---

# Log Bug Hunter — Procedure

## Required reads

@~/.teleclaude/docs/general/procedure/agent-job-hygiene.md
@docs/project/spec/jobs/log-bug-hunter.md

## Goal

Proactively discover errors in daemon logs before they become user-visible incidents.
Fix what can be fixed inline; dispatch what cannot to the bug pipeline.

This procedure is the automated equivalent of the "check current health" step from
the maintenance cadence — run continuously so weekly passes find fewer surprises.
The log-bug-hunter is one bug _source_ feeding the same pipeline that
`telec bugs report` feeds from interactive sessions.

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

4. Process every error. For each error, decide fix, dispatch, or record:
   - **Fix inline** when all are true:
     - Root cause is identifiable from the traceback and surrounding code.
     - Fix is within daemon codebase scope (Python files under `teleclaude/`).
     - Fix is small (a few lines), safe, and does not require a restart to verify.
     - Commit hooks (lint + tests) pass after the fix.
   - **Dispatch to bug pipeline** when any are true:
     - Fix requires architectural changes or touches multiple subsystems.
     - Root cause is unclear and needs investigation.
     - Fix requires service restart, config changes, or external coordination.
   - **Record only** when:
     - Error is transient and self-resolved (network blip, temporary resource pressure).
     - Error is already tracked by an existing bug (`todos/fix-*`) or todo.

5. Execute inline fixes:
   - Apply minimal fix.
   - Verify via commit hooks.
   - Commit with type `fix(scope): subject`.

6. Dispatch unfixable errors to the bug pipeline:
   - Check if a `todos/fix-{slug}/` already exists for this error class.
   - If yes, skip (do not create duplicates).
   - If no, run `telec bugs report "<description>" --slug fix-{slug}` where
     description includes: error summary, log excerpt, and attempted diagnosis.
   - The bug pipeline handles everything downstream: scaffold, branch,
     worktree, autonomous fix/review/merge.

7. Repeat steps 4–6 until every error from step 3 has been handled (fixed,
   dispatched, or recorded). Do not stop while unprocessed errors remain.

8. When all errors are processed, write the run report to
   `~/.teleclaude/jobs/log-bug-hunter/runs/{YYMMDD-HHMMSS}.md` and stop.

## Outputs

- Inline fixes committed on main (when safe and small).
- Bug reports dispatched via `telec bugs report` for errors requiring deeper work.
- Run report documenting all findings, actions, and skips.

## Recovery

1. If `instrukt-ai-logs` fails, write a report noting tool unavailability and stop.
2. If a fix breaks commit hooks, revert the fix, record the failure in the report,
   and dispatch the error to the bug pipeline instead.
3. If deduplication data is unavailable (no previous reports), treat all errors as new.
