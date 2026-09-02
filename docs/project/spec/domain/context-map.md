---
visibility: internal
description: Frozen v1 map of practical ownership areas used to classify current feature contracts.
---

# Context Map — Spec

## What it is

The v1 repository is a distributed Python monolith. Its contexts are semantic
ownership and dependency boundaries even when several of them share one process
or database deployment. Every domain decision, behavior, invariant, state model,
and vocabulary term belongs to exactly one context. Feature work is classified
against that owner; cross-context behavior composes the owners' published
contracts and never creates shared ownership.

## Canonical fields

- `agent_runtime`: live sessions, supervised agent processes, session-input
  execution, and runtime lifecycle. It does not own provider transport,
  presentation, identity decisions, or workflow state.
- `context`: documentation, agent assets, deployment, and context selection.
- `identity`: caller resolution, authentication evidence, and authorization
  identity. It does not own provider parsing or the domain action authorized.
- `integration`: external-provider and process-boundary transport,
  normalization, and translation. It does not own session, workflow, identity,
  or presentation policy merely because it carries those contexts' messages.
- `memory`: durable preference observations and retrieval.
- `session_mirrors`: transcript-derived historical search.
- `workflow`: todos, artifacts, lifecycle decisions, dependency ordering, and
  code-integration workflow.
- `config`: file-backed v1 configuration.
- `reconciliation`: installation and fleet convergence behavior.
- `presentation`: the ephemeral display state of TeleClaude's own UI clients —
  the TUI, the CLI, and the web frontend: local projections, caches, and
  rendering policy over data other contexts publish. It owns no published
  facts, no persistence, and no other context's semantics; it never redefines,
  validates, defaults, or recovers a publishing context's rules. Its observable
  behavior is bound by the feature specs its clients realize.

### Boundary contracts

- `integration` hands normalized session input to `agent_runtime` through the
  session-input delivery contract; it does not redefine runtime acceptance,
  queueing, or processing semantics.
- `integration` supplies authenticated caller signals to `identity`; identity
  owns their interpretation and returns the resolved principal.
- `workflow` requests session dispatch, observes session lifecycle, and consumes
  ephemeral dirty-path claimant evidence through `agent_runtime` contracts.
  `agent_runtime` owns the single-snapshot live-session attribution query;
  `workflow` owns coordination, custodianship, and resulting repository actions.
  Neither context implements the other's decisions or state transitions.
- `agent_runtime` publishes transcript and lifecycle facts consumed by
  `session_mirrors`; the mirror context never mutates live session truth.

<!-- planned:docs-tier-layering -->
- `context` resolves a caller's documentation reach from `identity`'s resolved
  person and resolved organizational membership, and from `config`'s project-tier
  declaration of an owning company. `identity` owns what those facts mean;
  `config` owns the declarations behind them; `context` owns only what a given
  set of relationships permits a caller to read, and never infers a relationship
  the resolved facts do not state.
<!-- /planned:docs-tier-layering -->
The daemon, handler, adapter, database, and background-worker labels are layers
or hosting mechanisms, not additional contexts. The TUI, the CLI, and the web
frontend are `presentation`'s hosting surfaces. Existing placement outside
these relationships is not precedent; the owning context and published contract
remain authoritative.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
