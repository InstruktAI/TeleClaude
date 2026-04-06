---
description: 'Bounded-context decomposition for the Architecture V2 target platform.'
id: 'project/design/architecture-v2/bounded-contexts'
scope: 'project'
type: 'design'
---

# Bounded Contexts — Design

## Required reads

- @docs/project/design/architecture-v2/overview.md

## Purpose

Define the major bounded contexts of the greenfield platform so the new system
has clear ownership boundaries instead of collapsing back into one runtime-heavy
ball of glue.

The goal is not purity for its own sake. The goal is to decide what must own
what, where storage truth belongs, and which responsibilities must be kept out
of each context.

## Inputs/Outputs

**Inputs:**

- the Architecture V2 target shape
- the current platform's ownership drift
- the need for a storage and service decomposition that supports local-first work

**Outputs:**

- the list of bounded contexts
- ownership and non-ownership boundaries for each context
- a storage ownership sketch
- cross-context rules that constrain the greenfield rebuild

## Invariants

- Every bounded context has a clear purpose, a clear storage ownership boundary,
  a clear public contract, and a short list of things it explicitly does not own.
- If a context description needs too many `and`s, it is too broad.
- Workflow cannot depend on Session Runtime availability for local correctness.
- Presentation cannot call storage directly; it must talk through
  application/service contracts.
- Session Ledger consumers do not parse transcripts directly.
- Context retrieval remains policy-first. Semantic search can be a helper, not
  the core truth model.
- Identity and auth live at boundaries. Domain/application services consume
  resolved identity context, not raw transport headers.

## Primary flows

### Guiding rule

The decomposition works only if ownership is explicit. The contexts below are
the target service seams for the greenfield platform.

### 1. Identity

**Owns:**

- people
- roles and permissions
- machine principals
- session principals
- API tokens and boundary credentials
- authentication policy at transport boundaries

**Does not own:**

- session runtime state
- workflow/todos
- context retrieval
- adapters

**Why it exists:**

Authentication and authorization are cross-cutting, but they should not drag
the daemon into owning all request handling. Identity should be a real service
boundary, not an emergent side effect of runtime state.

### 2. Session Runtime

**Owns:**

- agent sessions
- tmux/runtime orchestration
- live input/output streaming
- adapter-side session coordination
- current runtime presence and liveness

**Does not own:**

- local project bookkeeping
- workflow/todo mutation rules
- history projections
- knowledge storage

**Why it exists:**

This is the true daemon-shaped part of the system. It should focus on keeping
sessions alive, observable, and connected.

### 3. Workflow

**Owns:**

- todos
- roadmap items
- workflow artifacts
- workflow state machines
- work orchestration rules
- local bookkeeping operations

**Does not own:**

- long-running runtime sessions
- transcript ingestion
- web transport concerns
- knowledge retrieval

**Why it exists:**

This is the `telec todo` world. It must work locally, directly, and
transactionally with no daemon dependency for core operations.

### 4. Session Ledger

**Owns:**

- canonical session history
- transcript ingestion and normalization
- deterministic ordering
- session deltas/cursors
- session read models for history and replay

**Does not own:**

- tmux/session runtime lifecycle
- workflow/todos
- auth
- docs/knowledge curation

**Why it exists:**

Consumers should stop parsing transcript files directly. The ledger becomes the
system of record for session history.

### 5. Context and Knowledge

**Owns:**

- global/company/project knowledge
- snippet taxonomy
- context selection policy
- progressive disclosure rules
- ingestion pipelines for company and business information

**Does not own:**

- runtime session streaming
- todo state
- adapter lifecycle

**Why it exists:**

This preserves the strongest idea in the current platform: structured,
scope-aware, policy-driven context engineering instead of generic retrieval
spam.

### 6. Integration and Events

**Owns:**

- inbound webhooks
- event normalization
- outbox/inbox durability
- retries
- async delivery contracts
- handoff to workers/projectors

**Does not own:**

- domain business rules themselves
- local workflow state
- long-lived session orchestration

**Why it exists:**

Anything that crosses restart boundaries needs durable handoff. This context
turns side effects into a reliable system instead of a chain of in-process
calls.

### 7. Presentation

**Owns:**

- admin dashboards
- CRM UI
- marketing UI
- support UI
- public pages
- web-facing interaction surfaces

**Does not own:**

- core business logic
- durable workflow rules
- runtime orchestration

**Why it exists:**

Next.js belongs here. It is a strong presentation platform. It should not be
allowed to quietly become the whole backend.

### 8. Configuration

**Owns:**

- system configuration model
- project/company/global configuration overlays
- effective config computation
- config validation and versioning

**Does not own:**

- identity policy semantics
- workflow state
- knowledge content itself

**Why it exists:**

Configuration is important enough to deserve first-class ownership. It is too
central to leave as scattered files and ad hoc loader logic.

### 9. Agent Artifact Authoring and Distribution

**Owns:**

- agent artifact source models
- commands, skills, and agent-facing packaged artifacts
- artifact inflation/transformation rules
- `AGENTS.md` and related generated outputs
- sync/distribution pipelines
- deployed-runtime publication mechanics

**Does not own:**

- knowledge retrieval policy
- workflow/todo state
- session runtime orchestration
- general presentation logic

**Why it exists:**

This subsystem is too important to remain homeless. It is adjacent to Context
and Knowledge, but it is not the same thing. Context and Knowledge owns
canonical knowledge objects and retrieval policy. Artifact Authoring and
Distribution owns how agent-facing deliverables are built, packaged, inflated,
and published.

### Storage ownership sketch

This is the clean storage ownership map for the new platform:

- `identity` schema: Identity
- `runtime` schema: Session Runtime
- `workflow` schema: Workflow
- `ledger` schema: Session Ledger
- `context` schema: Context and Knowledge
- `integration` schema: Integration and Events
- `config` schema: Configuration
- `artifacts` schema: Agent Artifact Authoring and Distribution

One Postgres instance. Clear schema ownership. No random runtime truth leaking
into files.

### What this gives us

If these boundaries hold, the new system gains:

- local autonomy
- smaller restart blast radius
- cleaner contracts
- easier generation
- safer storage design
- a platform base that can grow into multiple business domains without becoming
  another monolith of accidental coupling

## Failure modes

- A context becomes too broad and starts describing multiple owners at once.
- Workflow logic leaks back into Session Runtime and reintroduces daemon
  dependence for local correctness.
- Presentation or adapters reach into storage directly and bypass service
  contracts.
- Session Ledger consumers fall back to raw transcript parsing and reintroduce
  fragile read models.
- Context and Knowledge turns into generic retrieval infrastructure instead of a
  policy-first system.
- Artifact authoring remains unowned and keeps accreting onto unrelated
  subsystems.
