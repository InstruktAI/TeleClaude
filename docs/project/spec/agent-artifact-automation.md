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

Background automation that waits for source activity to settle, validates the
source, and then rebuilds and publishes agent and documentation artifacts when
validation passes. Source that fails validation never replaces what is already
published, because publication is reached only after validation succeeds. One
pass runs at a time across every registered project, so two roots never write
the shared runtime destinations concurrently.

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
  its `AGENTS.master.md` / `AGENTS.global.md` files. Every relevant event resets
  a quiet period; the pass runs once activity settles. Generated sync outputs
  inside those trees are not triggers.
- **Serialization**: one publishing pass runs at a time across every registered
  root. Publication writes shared runtime destinations, so a second concurrent
  pass would corrupt them. Events arriving during a pass stay pending and
  produce one later pass once activity settles again.
- **Validation**: the watcher applies the same source validator an explicit
  invocation applies. Findings leave the previously published outputs in place
  and emit a watcher failure event; the next relevant source change retries
  automatically.

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
- Validating source and publishing it are distinct acts with no recorded
  relationship between them. Nothing records which source the published outputs
  were built from, so no reader can establish that what is live corresponds to
  what most recently validated.
- Publication is not transactional against an edit landing while it runs. The
  runtime can briefly hold a mixture of outputs until a later pass converges it.
  Waiting for activity to settle is the defense at entry; there is none for the
  pass's own duration.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->
