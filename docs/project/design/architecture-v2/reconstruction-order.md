---
description: 'Recommended reconstruction order for building the Architecture V2 platform from the spine outward.'
id: 'project/design/architecture-v2/reconstruction-order'
scope: 'project'
type: 'design'
---

# Reconstruction Order — Design

## Required reads

- @docs/project/design/architecture-v2/overview.md
- @docs/project/design/architecture-v2/bounded-contexts.md

## Purpose

Define the order in which the greenfield TypeScript platform should be built so
the reconstruction proceeds from stable ownership and storage truth instead of
repeating the current platform's runtime-centered growth pattern.

This is not an in-place migration order for the current Python codebase. It is
the recommended reconstruction order for rebuilding the platform from scratch
while carrying forward the best ideas from the current system.

## Inputs/Outputs

**Inputs:**

- the Architecture V2 target shape
- the bounded-context decomposition
- the need to sequence the rebuild so the platform spine is established first

**Outputs:**

- the staged reconstruction order
- the rationale for why each phase occurs when it does
- the parallel design streams that can proceed alongside implementation
- the anti-patterns the reconstruction must explicitly avoid

## Invariants

- Build the system from the spine outward.
- Do not start with shiny surfaces, adapters, or generated shells.
- Build the things that define the platform's truth first.
- The architecture must be locked before subsystem implementation begins.
- Workflow local autonomy must be restored before runtime-heavy concerns are
  rebuilt.
- Adapters and transport layers sit on top of domain, storage, and event
  boundaries rather than defining them.

## Primary flows

### Guiding principle

Build the system from the spine outward.

Do not start with shiny surfaces. Do not start with adapters. Do not start with
generated shells. Build the things that define the platform's truth first.

### Phase 0 — Lock the architecture

**Deliverables:**

- target architecture overview
- bounded contexts
- service boundaries
- storage ownership model
- contract strategy
- reconstruction order

**Why first:**

Without this, the rewrite will just grow another accidental monolith.

### Phase 1 — Platform spine

**Goal:**

Define the foundational contracts and storage model that every later subsystem
will rely on.

**Build:**

1. Postgres schema strategy
2. identity model
3. configuration model
4. domain/application layering conventions
5. contract conventions:
   - OpenAPI for sync
   - event schemas for async
6. event envelope contract:
   - common metadata fields
   - versioning rules
   - correlation/idempotency fields
   - producer/consumer typing conventions
7. legacy-to-v2 import specification template:
   - what existing state is preserved
   - what is transformed
   - what is intentionally dropped

**Result:**

The platform now has a stable core vocabulary.

### Phase 2 — Workflow core

**Goal:**

Rebuild local-first bookkeeping correctly before anything else.

**Build:**

1. workflow domain model
2. todo/roadmap/artifact storage model
3. transactional workflow operations
4. workflow state machine engine
5. local CLI path over application services
6. workflow import spec from current platform state

**Why this early:**

This restores the most important lost architectural promise: local project work
must continue even when runtime services are down.

### Phase 3 — Context and knowledge core

**Goal:**

Rebuild the progressive-disclosure context system on proper storage and
contracts.

**Build:**

1. taxonomy model
2. snippet/knowledge storage model
3. project/company/global ownership model
4. selection policy engine
5. ingestion pipeline contracts for business/company information
6. context/knowledge import spec from current platform state

**Why now:**

Context engineering is one of the strongest existing platform ideas. It should
become a first-class subsystem, not remain file-sprawl.

### Phase 4 — Session ledger

**Goal:**

Build the canonical session history layer.

**Build:**

1. ledger schema
2. canonical block/event model
3. ingestion/projector model
4. cursor/session sequence model
5. read contracts for history and deltas
6. ledger import/backfill spec from current platform state

**Why after workflow/context:**

The ledger is foundational, but it does not need to block local-first workflow.
It is a separate spine track that can be designed carefully once the platform's
general storage and contract conventions are established.

### Phase 5 — Event backbone

**Goal:**

Make side effects durable and restart-safe.

**Build:**

1. outbox/inbox model
2. worker contracts
3. retry and dead-letter behavior
4. projector/event consumer model
5. event observability

**Why here:**

By now, the platform has real domain services and storage, and the event
envelope/type contract already exists from Phase 1. The event backbone can be
built around actual boundaries instead of theoretical ones.

### Phase 6 — Session runtime

**Goal:**

Rebuild the daemon-shaped runtime around a much narrower ownership model.

**Build:**

1. session lifecycle services
2. tmux/runtime orchestration
3. live delta fanout
4. adapter runtime contracts
5. runtime observability and restart boundaries

**Why not first:**

The old system already proved that making runtime the center of everything leads
to overreach. In the new system, runtime must be built on top of clean domain
boundaries, not the other way around.

### Phase 7 — Thin API

**Goal:**

Expose the system without letting transport become the owner.

**Build:**

1. thin authenticated API shell
2. generated DTOs and clients where appropriate
3. request-to-service mapping
4. async receipt/enqueue patterns where needed

**Why here:**

The API should be a boundary over already-defined services, not the birthplace
of those services.

### Phase 8 — Presentation surfaces

**Goal:**

Bring Next.js and domain-specific interfaces online over stable services.

**Build:**

1. admin surfaces
2. workflow UI
3. session/history UI
4. CRM, support, and marketing domains
5. public and static surfaces

**Why later:**

The UI will move faster and cleaner if the service model beneath it is already
well formed.

### Phase 9 — Agent artifact authoring and distribution

**Goal:**

Rebuild the artifact system as an explicit subsystem instead of letting it
accrete onto unrelated contexts.

**Build:**

1. canonical artifact source model
2. inflation/transformation rules
3. sync/distribution services
4. deployed-runtime publication model
5. artifact import spec from the current platform

**Why here:**

The artifact system needs stable configuration, context, and contract models
under it. It should be rebuilt deliberately instead of being allowed to emerge
through ad hoc tooling.

### Phase 10 — Adapters and external interfaces

**Goal:**

Reconnect the platform to the outside world.

**Build:**

1. webhook ingestion
2. chat adapters
3. notifications
4. external automation hooks

**Why last:**

Adapters magnify architectural mistakes. They should sit on top of solid
runtime, event, and service boundaries.

### Parallel design streams

Some design work should proceed in parallel even if implementation is staged.

- Stream A: state-machine abstraction
- Stream B: config and effective-config strategy
- Stream C: knowledge ingestion and taxonomy refinement
- Stream D: auth and principal model
- Stream E: observability and operations model

### Summary

The recommended reconstruction order is:

1. Architecture
2. Platform spine
3. Workflow
4. Context and knowledge
5. Session ledger
6. Event backbone
7. Session runtime
8. API
9. Presentation
10. Agent artifacts
11. Adapters

That order gives the new system a stable center of gravity and prevents the
greenfield effort from repeating the current platform's main failure mode:
everything growing around the runtime until the runtime owns too much.

## Failure modes

1. Rewriting the daemon first and rebuilding the runtime as the center of the
   whole platform.
2. Generating transports before the service model exists.
3. Rebuilding presentation before domain and storage boundaries are fixed.
4. Letting the ledger or event backbone pull workflow local autonomy back into
   runtime dependence.
5. Leaving artifact authoring/distribution unowned instead of giving it an
   explicit bounded context from the start.
