---
description: "Daily job that scans each subscribed project's daemon logs and files a minimal bug report for every unsuppressed error signal."
visibility: 'public'
---

# Log Bug Hunter — Spec

## Required reads

@~/.teleclaude/docs/general/procedure/agent-job-hygiene.md
@~/.teleclaude/docs/software-development/procedure/maintenance/log-bug-hunter.md

## What it is

A maintenance job that proactively scans daemon logs for errors and files a
minimal bug report for each unsuppressed signal. It feeds the same bug pipeline
as `telec bugs report` — an automated bug _source_, not a fix system. It does
not investigate or fix inline; the diagnose/fix lifecycle owns each filed bug.
The procedure doc defines the scan workflow; this spec defines the job contract.

## Canonical fields

- `trigger`: daily scheduled run on the system schedule at the configured
  wall-clock time.
- `scope`: per registered project — one scan per project subscribed to
  `log_bug_hunter` under `jobs:` in that project's `teleclaude.yml`.
- `executor`: `jobs/log_bug_hunter.py` — an in-process `Job` run through the
  generic job path. There is no dedicated per-project service and no runner
  special-case branch.
- `orchestrator`: `teleclaude/services/project_jobs/orchestrator.py:ProjectJobOrchestrator`,
  consumed by the job to walk the `ProjectCatalogService` and run the per-project
  scan for each subscriber. The job consumes the shared orchestrator; it does not
  re-implement project discovery and does not iterate the catalog itself.
- `scan_source`: per-project log stream via
  `instrukt-ai-logs {project_slug} --since 1h --exclude git-wrapper`, run from
  `project_root`.
- `state_path`: `~/.teleclaude/state/log-bug-hunter/{project_slug}.json` — the
  per-project scan cadence and last outcome (`clean` / `suppressed` / `filed` /
  `failed`).
- `suppressions_path`: `~/.teleclaude/state/log-bug-hunter/{project_slug}.suppressions.json`
  — sibling to `state_path`, holding the project's known-issue suppression ledger.
  The job **only reads** this file; the `telec bugs suppress` / `unsuppress`
  CLI is its sole writer. Run-state (job-written) and suppressions
  (operator/agent-written) stay in separate single-writer files so neither
  clobbers the other.
- `output`: bug pipeline entry via the shared bug-report filing path — the same
  front door `telec bugs report` uses — for each unsuppressed error, scoped to the
  project being scanned. No session is dispatched and nothing is fixed inline.

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

1. Query the project's log stream for the last hour, excluding `git-wrapper`.
2. Scan the output line-by-line for candidate error signals (ERROR / CRITICAL /
   FATAL / EXCEPTION / Tracebacks), then subtract every line that matches an
   active suppression in the ledger.
3. File a minimal bug report through the shared filing path for each remaining
   non-suppressed error, skipping any error whose derived slug already has an
   active bug. A window whose every candidate line is suppressed is recorded as
   seen-and-skipped and files nothing. No session is dispatched and nothing is
   fixed inline — the diagnose/fix lifecycle owns each filed bug downstream.
