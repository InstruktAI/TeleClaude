---
description: 'Proactive log-scanning job that discovers daemon errors and files a minimal bug report for each unsuppressed signal.'
visibility: 'public'
---

# Log Bug Hunter — Procedure

## Required reads

@~/.teleclaude/docs/general/procedure/agent-job-hygiene.md

## Goal

Proactively discover errors in daemon logs before they become user-visible
incidents and file them into the bug pipeline. The log-bug-hunter is one
automated bug _source_ feeding the same pipeline `telec bugs report` feeds from
interactive sessions. It notices error signals and files them; it does not
investigate or fix inline — the diagnose/fix lifecycle owns each filed bug.

## Preconditions

1. The job runner started this session in a project root with this procedure's
   snippet ID as the job identity; the project's `project_slug` is readable from
   its configuration.
2. `instrukt-ai-logs {project_slug} --since <window> --exclude git-wrapper` is
   available and returns structured log output.
3. `telec bugs suppressions`, `telec bugs list`, and `telec bugs report` are
   available in this project.
4. Previous run records are available for the window and for deduplication in
   the job's run directory.

## Steps

1. Collect the logs this run owns for the current project:
   - The window starts at the newest previous run record in the job's run
     directory. With no previous record, the window is one schedule interval
     as declared in the job's `when` block. Express it as the duration from
     that start until now.
   - Run `instrukt-ai-logs {project_slug} --since <window> --exclude git-wrapper`,
     substituting the project slug of the project you are running in.
   - If no output or tool unavailable, write a "nothing to process" report and stop.

2. Extract error signals:
   - Identify lines containing errors, exceptions, tracebacks, and repeated warnings.
   - Group related log lines into distinct error instances.
   - Ignore informational and debug-level output.
   - If no error signals are found, write a "clean run" report and stop.

3. Drop what is already handled:
   - Skip (record only) errors whose signal matches an active entry in the
     project's suppression ledger (`telec bugs suppressions`). A suppressed signal
     is noted in the run report, never filed.
   - Skip errors already tracked by an existing bug (`telec bugs list`) or todo.
   - Read the most recent run reports (up to 3) and skip errors already reported
     unless they have new context (different traceback, increased frequency, new
     trigger).

4. File every remaining error:
   - Run `telec bugs report "<description>" --slug fix-{slug}` where the
     description carries the error summary and a log excerpt. Do not diagnose,
     do not fix, do not commit — the bug pipeline handles everything downstream.

5. Repeat steps 3–4 until every error from step 2 has been filed or recorded.
   Do not stop while unprocessed errors remain.

6. Write the run report and close the run as the Agent Job Hygiene procedure
   directs.

## Outputs

- A minimal bug report filed via `telec bugs report` for each unsuppressed,
  not-already-tracked error, scoped to the project the session runs in.
- Run report documenting all findings, filings, and skips.

## Recovery

1. If `instrukt-ai-logs` fails, write a report noting tool unavailability and stop.
2. If `telec bugs suppressions` fails, treat the ledger as empty for this run and
   note it in the report; never let a ledger failure silence a signal.
3. If a `telec bugs report` call fails, record the failure with the error summary
   in the report and continue with the remaining errors.
4. If deduplication data is unavailable (no previous reports), treat all errors as new.
