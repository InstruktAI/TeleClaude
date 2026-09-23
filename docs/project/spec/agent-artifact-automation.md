---
description: 'Automation that rebuilds and deploys agent artifacts when sources change.'
visibility: 'public'
---

# Agent Artifact Automation — Spec

## What it is


<!-- planned-change:retire-docs-watcher -->
Launchd automation that rebuilds and deploys agent artifacts when sources or docs
change in this repo.
<!-- change:retire-docs-watcher -->
Commit-boundary automation that rebuilds and deploys agent artifacts when a
commit changes agent sources or documentation in this repo. Nothing deploys
between a save and its commit.
<!-- /planned-change:retire-docs-watcher -->


## Canonical fields


<!-- planned-change:retire-docs-watcher -->
- **Service label**: `ai.instrukt.teleclaude.artifacts`
<!-- change:retire-docs-watcher -->
<!-- /planned-change:retire-docs-watcher -->
- **Trigger**: launchd WatchPaths on `agents/`, `docs/`, and `teleclaude.yml`; `.agents/` is delivery output and is never watched as a source
<!-- planned-change:retire-docs-watcher -->
- **Command**: the docs watcher (`teleclaude.cli.watch`), which deploys on change via the hidden, watcher-only `telec sync --skip-validation` — live reload never blocks; the commit gate is the real validation contract.
<!-- change:retire-docs-watcher -->
- **Command**: commit or merge maintenance invokes the internal publication action for its recorded range after the commit gate has validated it.
<!-- /planned-change:retire-docs-watcher -->


## Allowed values

- None.

## Known caveats


<!-- planned-change:retire-docs-watcher -->
- If the watcher is stopped, manual distribution is required.
- Generated artifacts are overwritten on the next automated run.
<!-- change:retire-docs-watcher -->
- A commit made on a host where the hook is not installed distributes nothing
  and surfaces no obligation. Recovery replays the recorded maintenance action;
  it never publishes the current working tree.
- Generated artifacts are overwritten on the next automated run.
<!-- /planned-change:retire-docs-watcher -->
