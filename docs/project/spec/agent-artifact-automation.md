---
id: 'project/spec/agent-artifact-automation'
type: 'spec'
scope: 'project'
description: 'Automation that rebuilds and deploys agent artifacts when sources change.'
---

# Agent Artifact Automation — Spec

## What it is

Launchd automation that rebuilds and deploys agent artifacts when sources or docs
change in this repo.

## Canonical fields

- **Service label**: `ai.instrukt.teleclaude.artifacts`
- **Trigger**: launchd WatchPaths on `.agents/`, `docs/`, and `teleclaude.yml`
- **Command**: `telec sync --warn-only`

## Allowed values

- None.

## Known caveats

- If the watcher is stopped, manual distribution is required.
- Generated artifacts are overwritten on the next automated run.
