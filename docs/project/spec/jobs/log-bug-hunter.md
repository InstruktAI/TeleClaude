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
- `scan_source`: daemon logs (instrukt-ai-logs / journald).
- `output`: bug pipeline entry via `telec bugs report` for each discovered error.
