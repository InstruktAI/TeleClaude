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

1. The generic runner is executing the `log_bug_hunter` job (`jobs/log_bug_hunter.py`),
   in-process, with no per-project service and no runner special-case branch.
2. The job consumes the shared `ProjectJobOrchestrator` to run one scan per
   project subscribed to `log_bug_hunter` under that project's `teleclaude.yml`.
3. `instrukt-ai-logs {project_slug} --since 1h` is available and returns
   structured log output from each project root.
4. Each project's suppression ledger
   (`~/.teleclaude/state/log-bug-hunter/{project_slug}.suppressions.json`) is
   readable; `telec bugs suppress` / `unsuppress` is its sole writer.

## Steps

For each subscribed project the orchestrator yields:

1. Collect the last hour of logs: `instrukt-ai-logs {project_slug} --since 1h`,
   run from the project root. On no output or tool failure, record the per-project
   outcome and move to the next project.
2. Extract candidate error signals — lines containing errors, exceptions,
   tracebacks (ERROR / CRITICAL / FATAL / EXCEPTION / Traceback). Ignore
   informational and debug output.
3. Subtract every candidate line that matches an active entry in the project's
   suppression ledger. A window whose every candidate line is suppressed is
   recorded as seen-and-skipped and files nothing.
4. For each remaining distinct error, file a minimal bug report through the
   shared bug-report filing path (the same front door `telec bugs report` uses),
   scoped to the project — unless an active bug for the derived slug already
   exists, in which case skip it to avoid duplicates. The report carries the
   error summary; the diagnose/fix lifecycle handles everything downstream.
5. Record the per-project outcome (`clean` / `suppressed` / `filed` / `failed`)
   in `~/.teleclaude/state/log-bug-hunter/{project_slug}.json`.

## Outputs

- A minimal bug report filed for each unsuppressed, not-already-tracked error,
  scoped to the project it was found in.
- Per-project scan state updated with the latest outcome.

## Recovery

1. If `instrukt-ai-logs` fails for a project, record the failure for that project
   and continue with the rest — per-project failures are isolated by the
   orchestrator and never stop the sweep.
2. If a suppression ledger is corrupt, the ledger module fails loud rather than
   silently emptying it; surface the error for that project and continue.
3. If a filing call fails, surface it as a job error for that project rather than
   dropping the signal silently.
