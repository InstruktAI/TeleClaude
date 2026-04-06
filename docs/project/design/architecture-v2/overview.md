---
description: 'Target architecture for the next-generation TeleClaude platform.'
id: 'project/design/architecture-v2/overview'
scope: 'project'
type: 'design'
---

# Architecture V2 Overview — Design

## Required reads

- @docs/project/design/architecture/system-overview.md
- @docs/project/design/architecture-v2/journey.md

## Purpose

This document defines the target architecture for the next TeleClaude platform.
It is intentionally high level. Its job is to establish the destination before
the refactor is decomposed into detailed designs, implementation plans, and
execution todos.

The central design goal is simple:

- restore clear boundaries,
- remove daemon/API overreach,
- keep local project work operational when runtime services are down,
- and provide a clean base for a broader small-business platform.

## Inputs/Outputs

**Inputs:**

- the current TeleClaude architecture
- the Architecture V2 rationale and drift analysis
- the need for a greenfield platform shape that supports broader business domains

**Outputs:**

- the target architectural destination
- the core principles and non-negotiable invariants
- the bounded-context and service/process model
- the storage, retrieval, state-machine, and contract strategies
- the migration direction that should follow from this target shape

## Invariants

- Local project bookkeeping works without daemon or API availability.
- The daemon is reduced to runtime coordination responsibilities.
- The API is a thin boundary, not the owner of business logic.
- Side effects move to durable event-driven processing.
- Operational truth moves from file sprawl into typed storage.
- Progressive disclosure remains the primary context-engineering model.
- No transport adapter owns workflow or business logic.
- Daemon restart must not block local project work.
- Cross-component side effects must survive component restarts.
- Storage and projections must be deterministic and versioned.

## Primary flows

### Strategic outcomes

The target system must provide these outcomes:

1. Local project bookkeeping works without daemon or API availability.
2. The daemon is reduced to runtime coordination responsibilities.
3. The API becomes a thin boundary, not the owner of business logic.
4. Side effects move to durable event-driven processing.
5. Operational truth moves from file sprawl into typed storage.
6. The platform becomes extensible enough to host business domains such as CRM,
   marketing, support, and administration on the same architectural base.

### Core principles

### 1. Local-first project autonomy

Project-local work must not depend on the TeleClaude daemon just to read or
write project state. Agents running inside tmux must be able to continue
working when daemon/API processes are restarted or temporarily unavailable.

### 2. Business logic lives in services, not transports

CLI commands, API routes, TUI actions, and webhook handlers are transport
adapters only. They authenticate, validate, translate, and call application
services. They do not define workflow behavior.

### 3. Daemon scope is narrow

The daemon exists to coordinate long-lived runtime concerns:

- session lifecycle,
- agent runtime integration,
- adapter orchestration,
- live fanout/broadcast,
- runtime subscriptions,
- background consumers that truly require an always-on runtime.

It is not the general owner of project bookkeeping or local command execution.

### 4. Event-driven side effects

Cross-component side effects must be durable and restart-safe. Projection,
notification, mirror replacement, ingestion, and background follow-up work
should use durable events instead of fragile in-process coupling.

### 5. Storage is operational truth

Operational state should live in typed storage, not ad hoc files. Human authoring
surfaces may still exist, but the canonical runtime truth belongs in databases
and service-owned schemas.

### Target stack

The current recommendation for the greenfield platform is:

- **Language**: TypeScript
- **Web/UI**: Next.js
- **Primary database**: Postgres
- **Sync contracts**: OpenAPI
- **Async contracts**: durable event schemas
- **Service style**: domain/application services with thin generated or mostly
  generated transport adapters

Next.js is a strong fit for web and admin surfaces, but it should not become the
entire backend runtime. Long-running orchestration, projection, and ingestion
work belong in dedicated services or workers.

### Bounded contexts

The target platform should be decomposed into these main bounded contexts.

### 1. Identity and Access

Owns:

- people and roles,
- machine/session principals,
- boundary authentication,
- authorization policy inputs.

Does not own:

- project bookkeeping,
- session runtime orchestration,
- transport-specific business behavior.

### 2. Session Runtime

Owns:

- session lifecycle,
- agent runtime coordination,
- tmux/runtime integration,
- live output/delta fanout,
- adapter runtime state.

Does not own:

- local project todo commands,
- history read models,
- documentation storage,
- UI/domain business logic.

### 3. Workflow

Owns:

- todos,
- roadmap state,
- artifacts,
- workflow state machines,
- local bookkeeping operations.

This context must support local CLI operation with no daemon dependency.

### 4. Session Ledger

Owns:

- canonical session history,
- transcript ingestion,
- deterministic ordering,
- consumer cursors and projections,
- history reads and replay surfaces.

This replaces direct transcript parsing by downstream consumers and eventually
supersedes the current mirrors approach.

### 5. Context and Knowledge

Owns:

- global/company/project knowledge objects,
- snippet taxonomy,
- retrieval policy,
- context selection and progressive disclosure,
- ingestion of company/project information dumps.

This is not generic RAG-first infrastructure. The retrieval model remains
policy-driven, scope-driven, and progressive-disclosure oriented.

### 6. Integration and Events

Owns:

- inbound webhooks,
- event normalization,
- durable outbox/inbox behavior,
- retries and replay,
- async work dispatch to workers/projectors.

### 7. Presentation Domains

Owns:

- admin dashboards,
- CRM,
- marketing surfaces,
- support/help-desk views,
- public/static sites,
- user-facing business interfaces.

These are consumers of the application services, not the owners of core logic.

### Service/process model

The target runtime should be independently restartable by boundary.

### 1. Local CLI

- direct caller of local application services,
- no daemon requirement for project-local operations,
- can authenticate locally where required.

### 2. API shell

- thin authenticated transport boundary,
- calls application services or submits async work,
- should be restartable without breaking local project bookkeeping.

### 3. Runtime daemon

- session runtime only,
- should be restartable without breaking local project bookkeeping,
- should not be overloaded with general business/service logic.

### 4. Workers

- projections,
- notifications,
- ingestion follow-up,
- async materialization,
- retry-safe event consumers.

### 5. Web

- Next.js-based domain interfaces,
- talks to application/API boundaries,
- should not own long-running orchestration.

### Storage model

The target platform should converge on one primary Postgres instance for the
single-machine scale we expect.

Recommended Postgres schema partitioning by bounded context:

- `identity`
- `runtime`
- `workflow`
- `ledger`
- `context`
- `integration`
- `projection`

This is one database with clean ownership, not many operational databases.

### What belongs in Postgres

- workflow/todo state,
- session ledger,
- projections,
- knowledge/snippet storage,
- company/project registry data,
- auth/session principals,
- event outbox/inbox,
- read-model caches that must survive restarts.

### What should stop being canonical files

- mirrors,
- operational snippets registry,
- todo/workflow state,
- session summaries,
- history projections,
- runtime metadata used by services.

### Retrieval and knowledge strategy

The current progressive-disclosure approach should remain the core model.

The target architecture should preserve:

- scope-aware selection,
- structured taxonomy,
- context layering,
- explicit policy-driven retrieval,
- operational memory injection.

This is stronger than naive “vector-search everything” RAG.

The target design is:

- structured primary retrieval,
- optional semantic retrieval as a secondary aid,
- ingestion pipelines that normalize external/company documents into canonical
  typed knowledge records.

### State machine strategy

State machines remain a strength of the platform and should be formalized rather
than discarded.

The target architecture should provide:

- a shared workflow/state-machine engine at the application layer,
- machine-specific definitions for workflow domains,
- explicit durable state transitions,
- clean separation between machine logic and transport delivery.

### Contract strategy

The contract-first model should be:

- OpenAPI for synchronous command/query surfaces,
- durable event schemas for asynchronous boundaries.

Generated or mostly generated code should exist at the transport layer only:

- DTOs,
- client SDKs,
- CLI/API shells,
- validation wrappers.

The domain model itself should remain handwritten and explicit.

### Migration direction

The refactor should not be approached as a single “rewrite everything” blob.
It should proceed by bounded context, with the architecture fixed first.

Recommended initial order:

1. Identity and access boundary model
2. Workflow/local todo autonomy
3. Session ledger
4. Context and knowledge storage
5. Durable event/integration layer
6. Presentation domain rollout

## Failure modes

- Local-first workflow autonomy is not restored and bookkeeping still depends on
  runtime services.
- The daemon is rebuilt as a broad service owner instead of a narrow runtime
  coordinator.
- The API grows beyond translation and starts owning application behavior.
- Storage truth remains fragmented across files, caches, and loosely typed
  projections.
- Retrieval collapses into generic RAG infrastructure and loses
  policy-driven progressive disclosure.
- Presentation layers are built before service and storage boundaries are stable.
