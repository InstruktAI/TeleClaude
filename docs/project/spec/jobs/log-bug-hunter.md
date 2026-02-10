---
id: 'project/spec/jobs/log-bug-hunter'
type: 'spec'
domain: 'software-development'
scope: 'project'
description: 'Hourly agent job that scans daemon logs for errors, fixes inline or promotes to todos.'
---

# Log Bug Hunter — Spec

## Required reads

@~/.teleclaude/docs/general/procedure/agent-job-hygiene.md
@~/.teleclaude/docs/general/procedure/maintenance/log-bug-hunter.md

## What it is

A maintenance job that proactively scans daemon logs for errors.
The procedure doc defines the full workflow. This spec defines the job contract.

## Canonical fields

### Files

| File                                                          | Role                                        |
| ------------------------------------------------------------- | ------------------------------------------- |
| `docs/project/spec/jobs/log-bug-hunter.md`                    | This spec — agent reads it for instructions |
| `docs/global/general/procedure/maintenance/log-bug-hunter.md` | Procedure — full workflow the agent follows |

## Allowed values

All domain values (priority levels, error classification, report format) are
defined in the procedure doc.

## Known caveats

- The agent cannot verify runtime fixes without a restart. Fixes that require
  restart are committed but flagged in the report for the next maintenance pass.
- Log output volume varies; noisy periods may hit context limits.
