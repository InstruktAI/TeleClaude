---
description: 'Automation that rebuilds and deploys agent artifacts when sources change.'
visibility: 'public'
---

# Agent Artifact Automation — Spec

## What it is

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

Launchd automation that rebuilds and deploys agent artifacts when sources or docs
change in this repo.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

Background automation that validates the latest stable source snapshot, then
rebuilds and deploys agent and documentation artifacts when that snapshot is
valid. Invalid or mid-edit source never replaces the last good deployment,
because promotion is reached only by a snapshot that already validated.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

## Canonical fields

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- **Service label**: `ai.instrukt.teleclaude.artifacts`
- **Trigger**: launchd WatchPaths on `.agents/`, `docs/`, and `teleclaude.yml`
- **Command**: the docs watcher (`teleclaude.cli.watch`), which deploys on change via the hidden, watcher-only `telec sync --skip-validation` — live reload never blocks; the commit gate is the real validation contract.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

- **Service label**: `ai.instrukt.teleclaude.docs-watch`.
- **Trigger**: a filesystem observer over every registered project root, waking
  on changes under the root's `docs/`, `agents/`, and `.agents/` trees and on
  its `AGENTS.master.md` / `AGENTS.global.md` files, debounced to a stable
  source snapshot. Generated sync outputs inside those trees are not triggers.
- **Validation**: the watcher applies the same source validator as the agent
  checkpoint. Findings retain the last good deployment and emit a watcher
  failure event; the next relevant source change retries automatically.
- **Deployment**: the watcher invokes explicit deploy mode only after validation
  succeeds, then records the deployed source generation once distribution
  completes.
- **Freshness**: any runtime reload that depends on changed agent artifacts waits
  until the recorded deployed generation covers the validated source generation.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

## Allowed values

- None.

## Known caveats

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- If the watcher is stopped, manual distribution is required.
- Generated artifacts are overwritten on the next automated run.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

- If the watcher is stopped, an operator may run explicit deploy mode for
  recovery; ordinary agent stop loops never own deployment.
- Generated artifacts are overwritten on the next successful validated run.
- Validation success and deployment freshness are distinct facts. A clean
  checkpoint never claims that a newer generation is already live.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->
