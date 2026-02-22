---
id: 'project/spec/jobs/log-bug-hunter'
type: 'spec'
domain: 'software-development'
scope: 'project'
description: 'Hourly agent job that scans daemon logs for errors, fixes inline or dispatches to bug pipeline.'
---

# Log Bug Hunter — Spec

## Required reads

@~/.teleclaude/docs/general/procedure/agent-job-hygiene.md
@~/.teleclaude/docs/general/procedure/maintenance/log-bug-hunter.md

## What it is

A maintenance job that proactively scans daemon logs for errors.
Feeds the same bug pipeline as `telec bugs report` — the log-bug-hunter
is an automated bug source, not a standalone fix system.
The procedure doc defines the full workflow. This spec defines the job contract.
