---
description: 'Automation that rebuilds and deploys agent artifacts when sources change.'
visibility: 'public'
---

# Agent Artifact Automation — Spec

## What it is


Launchd automation that rebuilds and deploys agent artifacts when sources or docs
change in this repo.


## Canonical fields


- **Service label**: `ai.instrukt.teleclaude.artifacts`
- **Trigger**: launchd WatchPaths on `.agents/`, `docs/`, and `teleclaude.yml`
- **Command**: the docs watcher (`teleclaude.cli.watch`), which deploys on change via the hidden, watcher-only `telec sync --skip-validation` — live reload never blocks; the commit gate is the real validation contract.


## Allowed values

- None.

## Known caveats


- If the watcher is stopped, manual distribution is required.
- Generated artifacts are overwritten on the next automated run.

