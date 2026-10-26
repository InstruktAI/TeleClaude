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

- `agent_runtime`: live sessions, supervised agent processes, session-input execution, runtime lifecycle, and the shared outcome/checkpoint handoff and persistence for scheduled agent procedures and script jobs. Agent reports are correlated with the currently open session. Each job's procedure or script owns the meaning of its optional checkpoint; `agent_runtime` stores it opaquely. It does not own job declarations or schedules, which `config` publishes, nor provider transport, presentation, identity decisions, or workflow state.

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

- `presentation`: display policy over data other contexts publish: local TUI
  and CLI projections, caches and rendering, and chat-message display lifetimes
  under `local/projects/teleclaude/policy/ux-message-cleanup`. It owns no
  published session facts or conversation-source persistence, and never
  redefines, validates, defaults or recovers another context's rules. Adapters
  execute its lifetime decisions through their existing delivery mechanics;
  transport and session-input acceptance retain their respective owners.

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

- `integration`'s consumers that tell people run on `event-catalog`'s consumer
  runtime and read a platform event's state from its lifecycle state
  vocabulary; they ask `config` whether a person's notification interests
  select an event type, ask `identity` who the platform administrators are or,
  for a published domain's events, whether each person's reach admits the
  event's origin, and narrow their audience within `identity`'s reach without
  widening it. They send through `integration`'s own person-addressed delivery.

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

- A dispatch names a procedure by its domain-qualified snippet ID, and the
  context whose contract governs the dispatch emits that ID: `workflow` emits
  its todo-lifecycle procedures, while `config` hands the scheduler the
  procedure a job declaration points at. `context` owns the publication those
  IDs resolve in and the reach that admits a source into it, read from
  `config`'s publishing declaration; `agent_runtime` owns resolving an emitted
  ID to one published procedure at entry, and owns the session record, title,
  and live-session attribution

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

### Domain specs

- `agent_runtime` — `local/projects/teleclaude/spec/domain/agent_runtime`
- `config` — `local/projects/teleclaude/spec/domain/config`
- `context` — `local/projects/teleclaude/spec/domain/context`
- `event-catalog` — `local/projects/teleclaude/spec/domain/event-catalog`
- `identity` — `local/projects/teleclaude/spec/domain/identity`
- `integration` — `local/projects/teleclaude/spec/domain/integration`
- `memory` — `local/projects/teleclaude/spec/domain/memory`
- `reconciliation` — `local/projects/teleclaude/spec/domain/reconciliation`
- `session_mirrors` — `local/projects/teleclaude/spec/domain/session_mirrors`
- `workflow` — `local/projects/teleclaude/spec/domain/workflow`
- `presentation` — no domain spec; implementation roots `teleclaude/cli/tui/`; its designs and decisions are listed under Presentation designs and decisions.

### Cross-cutting designs and decisions

- **local/projects/teleclaude/design/architecture/system-overview** — High-level architectural blueprint of TeleClaude components and data flow.
- **local/projects/teleclaude/design/architecture/layer-ownership** — Architectural layer boundaries, ownership rules, and the cross-cutting invariant that downstream layers receive fully resolved inputs.
- **local/projects/teleclaude/design/architecture/command-classification** — Response-mode classification for API commands, and the one crossing by which a request addressed to another computer executes there: synchronous results, receipt-backed asynchronous work that reports its outcome to the caller that asked, and the boundary relay that carries any request to the computer that owns its object.
- **local/projects/teleclaude/design/architecture/operation-receipts** — Receipt-first contract for asynchronous work: immediate operation_id, durable row, background execution, distinct outcome events, and delivery to the caller that asked.
- **local/projects/teleclaude/design/architecture/database** — SQLite persistence for sessions, hook outbox, memory, UX state, and agent metadata.
- **local/projects/teleclaude/design/architecture/performance-tuning** — Performance tuning decisions for the daemon under sustained API load, covering connection pooling, caching layers, event loop policy, and background worker pressure.
- **local/projects/teleclaude/design/architecture/cli-invocation-boundary** — The path from a shell to a telec command handler — which checkout's code runs, the one auth gate that alone precedes dispatch, and how a worktree exercises its own change without reaching live state.
- **local/projects/teleclaude/design/architecture/command-scope** — Which root a telec command acts on when it runs inside a slug worktree — the worktree for work on the change itself, the shared project for anything that exists once — resolved for every command by one resolver.
- **local/projects/teleclaude/design/architecture/api-server** — The shared local HTTP and WebSocket API exposes viewer-authorized daemon state to UI clients and routes mutations through their owning command contracts.
- **local/projects/teleclaude/design/architecture/cache-system** — The boundary among authoritative source owners, daemon cache materialization, and UI state projection.
- **local/projects/teleclaude/design/architecture/human-message-envelope** — Shared semantic envelope for human-facing authorship, provenance, occurrence time, and surface-specific rendering.
- **local/projects/teleclaude/design/architecture/procedure-activation** — How a published procedure's event subscriptions select platform events by type pattern and by the kind of home the procedure answers, and how the computer that emitted a matching event starts or wakes that procedure's standing agent in the event's origin through one generic command — an independent event consumer composed from existing event, dispatch, session, operation, and identity contracts.
- **local/projects/teleclaude/design/architecture/conversation-memory-pipeline** — Composition of retained conversation sessions, session-owned mirrors and identity-addressed memory extraction at closure.
- **local/projects/teleclaude/design/architecture/mcp-credential-ownership** — Composition of verified person identity, personal secret ownership, and MCP runtime lease isolation.
- **local/projects/teleclaude/design/architecture/assistant-connector-boundary** — How an agent session reaches an external mail or calendar connector: the person binding it consumes rather than derives, the layer each responsibility sits in, and how the settings prohibition is held by the connector's own controls.
- **local/projects/teleclaude/design/architecture/deployment-pipeline** — Architecture of the deployment pipeline: a single ingress terminates external webhooks and relays them to the cluster bus, and each installation converges by its channel — reacting to relayed signals and reading its source on an interval — with breaking releases held for its installation inspector.
- **local/projects/teleclaude/design/architecture/web-console** — The operator web console — a native web service on the master that authenticates people, serves the console page, terminates the pinned LAN hop from the ingress computer's reverse proxy, and acts on the daemon over its Unix socket with carried identity.
- **local/projects/teleclaude/design/architecture/work-item-conversation** — How the completed turns of the sessions working a GitHub-backed work item reach that item's issue or pull request, cleaned, in completion order and once, without touching the sessions or the record.
- **local/projects/teleclaude/design/architecture-v2/data-upcasting** — Historical reference anchor for the retired v2 data-upcasting design named by an immutable ADR.
- **local/projects/teleclaude/design/architecture-v2/skills-personal-curation** — Historical reference anchor for the retired v2 personal skill-curation design named by an immutable ADR.
- **local/projects/teleclaude/adr/0054-v1-is-the-system** — v1 (Python) is the canonical running system; the v2 Rust rewrite is retired as a destination, and capabilities conceived under v2 that are genuinely needed are built in v1.
- **local/projects/teleclaude/adr/0062-commands-carry-target-computer** — Commands carry their target computer and the serialized command is the cross-computer wire format; the parallel Redis command-string vocabulary and per-command remote wrappers are retired.
- **local/projects/teleclaude/adr/0068-vnext-replaces-v1-through-authoritative-cuts** — Replace v1 with a separately built Rust vNext through successive authoritative vertical cuts and no compatibility bridges.
- **local/projects/teleclaude/adr/0069-vnext-authority-lives-in-separate-repository** — The TeleClaudeNext repository is the sole authority for vNext architecture, program state, reviews, and implementation.
- **local/projects/teleclaude/adr/0074-v1-is-maintained-until-vnext-adoption** — v1 is maintained with bug fixes and operator-needed changes until a vNext cut adopts a journey, replacing the approved-P0-only maintenance gate.
- **local/projects/teleclaude/adr/0080-cli-flag-recognition-derives-from-the-surface-declaration** — telec option recognition is derived at runtime from the declared CLI surface through one shared parser; argparse and a third-party CLI framework are not adopted.
- **local/projects/teleclaude/adr/0095-authority-follows-human-owned-consequences** — Decision authority follows the material consequence a person can evaluate, while technical and process mechanisms remain agent-owned.
- **local/projects/teleclaude/adr/0098-async-work-always-carries-a-receipt** — Work that finishes after its response carries a durable operation row, distinct success and failure events, and delivery to the caller that asked for it.
- **local/projects/teleclaude/adr/0110-an-event-activated-procedure-runs-where-its-event-originated** — An event-activated procedure runs on the computer its event originated on, in the home its subject names, with platform events answered in the platform's own checkout; a computer that merely shares the home never runs the same work.
- **local/projects/teleclaude/adr/0119-the-cli-never-waits-on-a-receipt** — A receipt-backed CLI command returns its receipt without waiting, so every daemon-backed command ends either accepted or not accepted and the caller's wake is the only path an outcome takes back.
- **local/projects/teleclaude/adr/0121-computer-addressed-requests-cross-as-one-relay-command** — An API request addressed to another computer is carried whole to that computer as one relay command at the API boundary, instead of each route opting into its own forwarding.
- **local/projects/teleclaude/adr/0122-the-web-console-sits-behind-the-single-itsup-fleet** — The web console is reached through the one itsUP fleet on the ingress computer, which terminates public TLS and re-encrypts a pinned hop to a web service running natively on the master; webhooks stay on the ingress computer's daemon.

### Presentation designs and decisions

- **local/projects/teleclaude/design/architecture/tui-state-layout** — State-driven layout model for the Telec TUI sessions and preparation views.
- **local/projects/teleclaude/design/architecture/cache** — Daemon-owned in-memory snapshots materialize local source state and remote cluster state for immediate reads and UI projection.
- **local/projects/teleclaude/design/architecture/agent-activity-streaming-target** — Target architecture for unified agent activity streaming across Telegram and TUI clients.
- **local/projects/teleclaude/design/ux/session-highlight** — Session highlight system for user attention in TUI.
- **local/projects/teleclaude/design/ux/session-highlight/implementation-plan** — Implementation plan for explicit reason-driven highlight system.
- **local/projects/teleclaude/design/ux/session-preview-sticky** — Preview and sticky session interaction model for TUI pane management.
- **local/projects/teleclaude/design/ux/tui-animations** — Physical architecture and animation catalog for the TUI cinematic rooftop banner.
- **local/projects/teleclaude/adr/0014-tier-triggered-pane-layout** — The Sessions-view pane renderer swaps same-tier cells in place and minimally reflows on tier change, replacing the destroy-and-rebuild + select-layout even-horizontal approach; one canonical state owner enforces invariant I1.
- **local/projects/teleclaude/adr/0082-remove-nextjs-frontend** — The Next.js browser frontend is removed from the repository rather than fixed or maintained.

## See Also

- docs/local/adr/0069-vnext-authority-lives-in-separate-repository.md
