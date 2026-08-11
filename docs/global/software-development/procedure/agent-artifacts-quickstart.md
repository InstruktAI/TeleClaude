---
description: 'Quickstart for authoring and distributing agent artifacts.'
visibility: 'public'
---

# Agent Artifacts Quickstart — Procedure

## Goal

Get an agent artifact authored and distributed to tool-specific outputs.

## Preconditions

- Access to the target repository and artifact scopes.
- Artifact schema references available.

## Steps

1. Choose the scope (global or project) for the artifact.
2. Author or update the artifact in the chosen scope following the schema.
3. Validate snippet structure and required reads.

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

4. Run `telec sync` to generate and deploy outputs.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

4. Run bare `telec sync` to validate the source. The watcher generates and deploys
   outputs after source activity settles.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

## Outputs

- Authored artifact in the chosen scope.

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- Generated tool-specific outputs after `telec sync`.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

- Watcher-published tool-specific outputs after validation passes.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

## Recovery

- Editing generated output files directly — they get overwritten on next distribution run.

<!-- planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->

- Forgetting to run distribution after changing source artifacts — runtimes will use stale outputs.

<!-- change:state-validated-checkpoints-and-watcher-owned-deploy -->

- A watcher deployment that reports validation findings — correct the source; the prior
  runtime outputs remain in use until a later settled pass succeeds.

<!-- /planned-change:state-validated-checkpoints-and-watcher-owned-deploy -->
