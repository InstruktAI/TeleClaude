---
visibility: internal
description: Frozen v1 map of practical ownership areas used to classify current feature contracts.
---

# Context Map — Spec

## What it is

The v1 repository is a distributed Python monolith. Its domain names are
practical ownership labels for feature inventory, not an enforced service or
dependency graph. Feature work is classified against the owning domain spec;
cross-domain behavior remains grounded in current feature specs and code.

## Canonical fields

- `agent_runtime`: live sessions and supervised agent processes.
- `context`: documentation, agent assets, deployment, and context selection.
- `identity`: caller resolution and authentication evidence.
- `integration`: provider and process-boundary integration behavior.
- `memory`: durable preference observations and retrieval.
- `session_mirrors`: transcript-derived historical search.
- `workflow`: todos, artifacts, lifecycle, and integration workflow.
- `config`: file-backed v1 configuration.
- `reconciliation`: installation and fleet convergence behavior.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
