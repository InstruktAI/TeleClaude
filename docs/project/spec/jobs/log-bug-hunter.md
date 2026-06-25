---
description: "Daily job that scans each subscribed project's daemon logs and files a minimal bug report for every unsuppressed error signal."
visibility: 'public'
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
- `suppressions_path`: `~/.teleclaude/state/log-bug-hunter/{project_slug}.suppressions.json`
  — sibling to `state_path`, holding the project's known-issue suppression ledger.
  The service **only reads** this file; the `telec bugs suppress` / `unsuppress`
  CLI is its sole writer. Run-state (service-written) and suppressions
  (operator/agent-written) stay in separate single-writer files so neither
  clobbers the other.
- `output`: bug pipeline entry via `telec bugs report` for each discovered error,
  scoped to the project the session is dispatched into.

### Suppression ledger

A per-project allowlist of known-issue signatures the scan treats as already
triaged. Stored at `suppressions_path` as a typed, versioned JSON document of the
shape `{version, suppressions: [...]}`. Each suppression carries:

- `id`: stable identifier generated at registration; the `unsuppress` handle.
- `pattern`: the signature matched against a candidate error line.
- `match`: `substring` (default, literal) or `regex` (opt-in).
- `disposition`: `expected` or `wontfix`, defaulting to `wontfix` — record-only
  intent, no effect on matching.
- `reason`: human-readable justification.
- `source_bug`: optional slug of the bug whose triage produced the suppression.
- `created_by`, `created_at`: provenance.
- `expires_at`: optional ISO-8601 expiry. A suppression is **active** when
  `expires_at` is unset or still in the future; an elapsed expiry is inert and
  its signal is filed again.

Matching is pure allowlist: the code only tests a candidate line against the
authored pattern and never grades whether a line is meaningful. The pattern
targets the invariant signal (a stable reason token), not volatile values. A
regex pattern is validated at registration; a pattern that fails to compile at
read time is skipped, never crashing the scan.

The operator surface is the `telec bugs` front door: `telec bugs suppress
"<pattern>" --reason <r> [--match substring|regex] [--disposition expected|wontfix]
[--project <name>] [--source-bug <slug>] [--expires <when>]` registers one,
`telec bugs suppressions [--project <name>]` lists the project's ledger, and
`telec bugs unsuppress <id>` removes one.

### Per-invocation behavior

1. Query the project's log stream for the last hour.
2. Scan the output line-by-line for candidate error signals (ERROR / CRITICAL /
   FATAL / EXCEPTION / Tracebacks), then subtract every line that matches an
   active suppression in the ledger.
3. Dispatch a new bug-hunter session into `project_root` only when at least one
   non-suppressed candidate line remains and no `log_bug_hunter` session is
   already active for that project. A window whose every candidate line is
   suppressed is recorded as seen-and-skipped and dispatches nothing.
