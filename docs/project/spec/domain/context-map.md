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

### Boundary contracts

- `integration` hands normalized session input to `agent_runtime` through the
  session-input delivery contract; it does not redefine runtime acceptance,
  queueing, or processing semantics.
- `integration` supplies authenticated caller signals to `identity`; identity
  owns their interpretation and returns the resolved principal.
<!-- planned-change:telec-code-dirty-path-owners -->
- `workflow` requests session dispatch and observes session lifecycle through
  `agent_runtime` contracts; neither context implements the other's state
  transitions.
<!-- change:telec-code-dirty-path-owners -->
- `workflow` requests session dispatch, observes session lifecycle, and consumes
  ephemeral dirty-path claimant evidence through `agent_runtime` contracts.
  `agent_runtime` owns the single-snapshot live-session attribution query;
  `workflow` owns coordination, custodianship, and resulting repository actions.
  Neither context implements the other's decisions or state transitions.
<!-- /planned-change:telec-code-dirty-path-owners -->
- `agent_runtime` publishes transcript and lifecycle facts consumed by
  `session_mirrors`; the mirror context never mutates live session truth.

The daemon, handler, adapter, CLI, TUI, database, and background-worker labels
are layers or hosting mechanisms, not additional contexts. Existing placement
outside these relationships is not precedent; the owning context and published
contract remain authoritative.

<!-- planned:tui-agent-availability-state-coherence -->
TeleClaude's own UI clients — the TUI, the CLI, and the web frontend — are
presentation clients, not bounded contexts. A UI client owns only its ephemeral
display state: local projections, caches, and rendering policy over data the
owning contexts publish. It never redefines, validates, defaults, or recovers a
publishing context's semantics, and no context owns a UI client's ephemeral
state. The observable behavior of a UI client is bound by the feature-spec
contracts it realizes. This mirrors the vNext ruling that UI surfaces are
clients of published projections owning only ephemeral UI state.
<!-- /planned:tui-agent-availability-state-coherence -->

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
