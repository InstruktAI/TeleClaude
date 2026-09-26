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
  the TUI and the CLI: local projections, caches, and
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
<!-- planned-change:integrator-stranded-dirt-by-asking -->
- `workflow` requests session dispatch, observes session lifecycle, and consumes
  ephemeral dirty-path claimant evidence through `agent_runtime` contracts.
  `agent_runtime` owns the single-snapshot live-session attribution query;
  `workflow` owns coordination, custodianship, and resulting repository actions.
  Neither context implements the other's decisions or state transitions.
<!-- change:integrator-stranded-dirt-by-asking -->
- `workflow` requests session dispatch, observes session lifecycle, and messages
  live sessions through `agent_runtime` contracts. `workflow` owns the
  integrator's coordination and resulting repository actions, including the
  resolution of dirty repository-root paths. Neither context implements the
  other's decisions or state transitions.
<!-- /planned-change:integrator-stranded-dirt-by-asking -->

- `agent_runtime` publishes transcript and lifecycle facts consumed by
  `session_mirrors`; the mirror context never mutates live session truth.

- `context` resolves a caller's documentation reach from `identity`'s resolved
  person and resolved organizational membership, and from `config`'s project-tier
  declaration of an owning company. `identity` owns what those facts mean;
  `config` owns the declarations behind them; `context` owns only what a given
  set of relationships permits a caller to read, and never infers a relationship
  the resolved facts do not state.

- The sealed commit surface (`agent_runtime`) reads tier answers from `config`
  at two coordinates — the repository root's declared tier, and the acting
  invocation context root's invocation-context and project-subscription
  answers. `config` owns those facts and their axes, which grant no operation;
  `agent_runtime` owns the decisions taken from them — seal coverage, commit
  availability, and gate selection — under its own approved product contract,
  and never derives a permission the axes do not publish.
- The commit boundary (`agent_runtime`) consumes `reconciliation`'s published
  retained-set answer as a term of commit eligibility. `reconciliation` owns
  membership — which of the repository's paths are retained; `agent_runtime`
  asks, and neither decides membership nor substitutes an answer where none is
  published.
- A command's name belongs to the context that owns the command, and that
  context emits it domain-qualified; the shared name table holds the values
  without owning them. Semantic owner and corpus domain are independent:
  `workflow` owns its todo-lifecycle names and emissions, while `config` owns
  the configured-job command and the scheduler's `general/run-job`
  emission. Each other command follows the context named by its governing
  contract. `context` owns the corpus those names are laid out in and the reach
  that admits a source into it, read from `config`'s publishing declaration;
  `agent_runtime` owns resolving an emitted name to one corpus document at
  dispatch, and owns the session record, title, and live-session attribution
  query that carry and match the dispatched value, which callers such as
  `workflow` consume. None restates another's rule: a caller never inspects the
  corpus or matches sessions itself, `context` never composes a dispatch, and
  `agent_runtime` never decides reach or command vocabulary.

<!-- planned:procedure-event-activation -->
- `context` publishes each procedure's declared event subscriptions and
  publication tier; `integration` turns them into routing contracts, stamps
  each event with the company `config` declares for its source, and on each
  computer matches only when `config` answers that the company is configured
  there. `integration` hands each resulting activation to `agent_runtime` as a
  command addressed to its own computer and never starts, addresses, or
  inspects a session. `agent_runtime` owns the activation runner and each
  session's company, consuming `identity`'s membership resolution; `identity`
  resolves the company context a tool inside a session reads from the session
  record that session's id names and its own membership resolution, and
  copies none of it into the session identity document. None restates
  another's rule: `integration` never
  decides whether an agent stands, `agent_runtime` never matches events or reads
  procedure metadata, and `identity` never chooses a session's company.
<!-- /planned:procedure-event-activation -->

The daemon, handler, adapter, database, and background-worker labels are layers
or hosting mechanisms, not additional contexts. The TUI and the CLI are
`presentation`'s hosting surfaces. Existing placement outside
these relationships is not precedent; the owning context and published contract
remain authoritative.

## See Also

- docs/project/adr/0069-vnext-authority-lives-in-separate-repository.md
