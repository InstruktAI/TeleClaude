---
description: 'Standard commands for operating the TeleClaude installation and its daemon service.'
visibility: 'public'
---

# Service Management — Procedure

## Goal

Operate the installation's daemon safely and consistently.

## Preconditions

- Any directory; `telec app` acts on the installation wherever it is run.

## Steps

1. Start service: `telec app start`.
2. Stop service (emergency only): `telec app stop`.
3. Restart service: `telec app restart`.
4. Check status and the active release: `telec app status`.
5. Install a pushed revision no channel reaction installs: `telec app install <revision>`; return one step after an install that migrated nothing: `telec app rollback` (`local/projects/teleclaude/spec/feature/reconciliation/installed-releases`).
6. Review logs: `instrukt-ai-logs teleclaude --since 2m`.

## Outputs

- Service state updated and verified.

## Recovery

- If the daemon crash-loops, use `telec app stop`, inspect logs, and fix the root cause in a project before installing the fix.
