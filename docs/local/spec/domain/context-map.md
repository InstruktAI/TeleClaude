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

- `event-catalog`: the platform event stream's envelope shape, the facts every
  event states about itself — its type, source and origin, subject, related
  references, and causation — the kinds of thing a reference can name, the
  vocabulary of states a platform event reports, the event type declarations
  the catalog is generated from, the one type-pattern matcher, and the consumer
  runtime: each consumer's progress through the stream, duplicate protection,
  retry, and dead letter. It owns no other context's event meaning and no other
  context's reaction.

### Boundary contracts

- `integration` hands normalized session input to `agent_runtime` through the
  session-input delivery contract; it does not redefine runtime acceptance,
  queueing, or processing semantics.
- `integration` supplies authenticated caller signals to `identity`; identity
  owns their interpretation and returns the resolved principal.
- `workflow` requests session dispatch, observes session lifecycle, and messages
  live sessions through `agent_runtime` contracts. `workflow` owns the
  integrator's coordination and resulting repository actions, including the
  resolution of dirty repository-root paths. Neither context implements the
  other's decisions or state transitions.

- `agent_runtime` publishes transcript and lifecycle facts consumed by
  `session_mirrors`; the mirror context never mutates live session truth.

<!-- planned-change:domain-notifications -->

- `identity` publishes each principal's reach — which records it may see, by
  each record's subject, the subject's owner, and the principal it is recorded
  under — built from its own membership facts and `config`'s project ownership.
  The surfaces that show records to principals consume it: `agent_runtime`
  (session listings, live session updates, and operation status),
  `session_mirrors` (history), `memory` (observation reads), `context`
  (documentation depth), and `config`'s project listing. Each consumer owns
  which facts its records carry and its own audience facts, such as public and
  person-local documentation; none adds, relaxes, or re-derives reach, and
  `identity` never decides a consumer's audience facts.

<!-- change:domain-notifications -->

- `identity` publishes each principal's reach — which records it may see, by
  each record's subject, the subject's owner, and the principal it is recorded
  under — built from its own membership facts and `config`'s project ownership.
  The surfaces that show records to principals consume it: `agent_runtime`
  (session listings, live session updates, and operation status),
  `session_mirrors` (history), `memory` (observation reads), `context`
  (documentation depth), `config`'s project listing, and `integration`'s
  messages about published domains' events. Each consumer owns
  which facts its records carry and its own audience facts, such as public and
  person-local documentation; none adds, relaxes, or re-derives reach, and
  `identity` never decides a consumer's audience facts.

<!-- /planned-change:domain-notifications -->
<!-- planned-change:domain-notifications -->

- `integration`'s consumers that tell people run on `event-catalog`'s consumer
  runtime and read a platform event's state from its lifecycle state
  vocabulary; they ask `config` whether a person's notification interests
  select an event type, ask `identity` who the platform administrators are, and
  narrow their audience within `identity`'s reach without widening it. They
  send through `integration`'s own person-addressed delivery.

<!-- change:domain-notifications -->

- `integration`'s consumers that tell people run on `event-catalog`'s consumer
  runtime and read a platform event's state from its lifecycle state
  vocabulary; they ask `config` whether a person's notification interests
  select an event type, ask `identity` who the platform administrators are or,
  for a published domain's events, whether each person's reach admits the
  event's origin, and narrow their audience within `identity`'s reach without
  widening it. They send through `integration`'s own person-addressed delivery.

<!-- /planned-change:domain-notifications -->

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

- `context` publishes each procedure's declared subscription patterns, the home
  kind it answers, and its publication tier; `integration` runs one platform
  event consumer that, on the computer that emitted an event, matches the
  event's type and origin against them with `event-catalog`'s type-pattern
  matcher, and hands each resulting activation to `agent_runtime` as a command
  addressed to its own computer; it never starts, addresses, or inspects a
  session. `agent_runtime` owns the activation runner, asks `config` whether the
  project, person, or company the event's origin names is registered on that computer and where its home folder is, and owns
  each session's company, consuming `identity`'s membership resolution;
  `identity` resolves the company context a tool inside a session reads from
  the session record that session's id names and its own membership resolution,
  and copies none of it into the session identity document. None restates
  another's rule: `integration` never decides whether an agent stands,
  `agent_runtime` never matches events for activation or reads procedure
  metadata, and `identity` never chooses a session's company.

- Every context that emits onto the platform event stream states each event's
  subject — the one thing its act concerned — and its origin — the registered
  project, person, or company the act happened in, none when it happened in none,
  or unknown when the event does not carry it — and owns those choices as part of
  its emission invariant. No event states a home: a consumer that works in one
  resolves it from the origin on its own computer. `event-catalog` composes the rest of the envelope at
  emission from the owners' published answers. From `identity`, it takes the
  caller session resolved at the request boundary for the request that produced
  the event, held for the request's whole duration, and references that session.
  From `config`, it takes the registered-subject vocabulary and a project origin's
  declared owner. It restates none of their rules, validates nothing, and
  decides no audience. Consumers read the event's attributes, and receipt
  decisions stay with the consuming contexts.

The daemon, handler, adapter, database, and background-worker labels are layers
or hosting mechanisms, not additional contexts. The TUI and the CLI are
`presentation`'s hosting surfaces. Existing placement outside
these relationships is not precedent; the owning context and published contract
remain authoritative.

## See Also

- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
