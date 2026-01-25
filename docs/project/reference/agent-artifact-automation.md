---
id: reference/agent-artifact-automation
type: reference
scope: project
description: Automation that rebuilds and deploys agent artifacts when sources change.
---

# Agent Artifact Automation — Reference

## What it is

Launchd automation that rebuilds and deploys agent artifacts when sources or docs
change in this repo.

## Canonical fields

- **Service label**: `ai.instrukt.teleclaude.artifacts`
- **Trigger**: launchd WatchPaths on `.agents/`, `docs/`, and `teleclaude.yml`
- **Command**: `scripts/sync_resources.py --warn-only` then `scripts/distribute.py --deploy`

## Allowed values

- None.

## Known caveats

- If the watcher is stopped, manual distribution is required.
- Generated artifacts are overwritten on the next automated run.
