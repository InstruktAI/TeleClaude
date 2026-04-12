---
id: 'project/spec/jobs/log-bug-hunter'
type: 'spec'
domain: 'software-development'
scope: 'project'
description: 'Daily agent job that scans daemon logs for errors, fixes inline or dispatches to bug pipeline.'
---

# Log Bug Hunter — Spec

## Required reads

@~/.teleclaude/docs/general/procedure/agent-job-hygiene.md
@~/.teleclaude/docs/software-development/procedure/maintenance/log-bug-hunter.md

## What it is

A maintenance job that proactively scans daemon logs for errors.
Feeds the same bug pipeline as `telec bugs report` — the log-bug-hunter
is an automated bug source, not a standalone fix system.
The procedure doc defines the full workflow. This spec defines the job contract.

## Canonical fields

- `trigger`: daily scheduled run at the configured wall-clock time.
- `scope`: per registered project — one invocation per project subscribed to
  `log_bug_hunter` under `jobs:` in that project's `teleclaude.yml`.
- `executor`: `teleclaude/services/log_bug_hunter_service.py:LogBugHunterService`,
  bound to a single `project_root` and `project_slug`.
- `orchestrator`: `teleclaude/services/project_jobs/orchestrator.py:ProjectJobOrchestrator`
  walks the `ProjectCatalogService` and dispatches the executor per subscribed
  project; the service itself does not iterate projects.
- `scan_source`: per-project log stream via
  `instrukt-ai-logs {project_slug} --since 1h`, run from `project_root`.
- `state_path`: `~/.teleclaude/state/log-bug-hunter/{project_slug}.json`.
- `output`: bug pipeline entry via `telec bugs report` for each discovered error,
  scoped to the project the session is dispatched into.

### Per-invocation behavior

1. Query the project's log stream for the last hour.
2. Scan the output for candidate error signals (ERROR / CRITICAL / FATAL /
   EXCEPTION / Tracebacks).
3. Dispatch a new bug-hunter session into `project_root` only when signals are
   present and no `log_bug_hunter` session is already active for that project.
