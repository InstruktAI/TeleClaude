---
description: 'Why TeleClaude needs an architecture v2 and what has drifted in the current system.'
id: 'project/design/architecture-v2/journey'
scope: 'project'
type: 'design'
visibility: 'public'
---

# Architecture V2 Journey — Design

## Required reads

- @docs/project/design/architecture/system-overview.md

## Purpose

This document captures the journey to Architecture V2: what grew well, what
drifted, and why a clean architectural reset is justified.

It exists so the refactor preserves the beauty of the system that emerged while
explicitly rejecting the accidental coupling that accumulated around it.

## Inputs/Outputs

**Inputs:**

- the current TeleClaude system shape
- recent investigations into daemon/API/CLI coupling
- the platform's strongest existing product and architecture ideas

**Outputs:**

- the rationale for Architecture V2
- the list of qualities worth preserving
- the main forms of architectural drift that justify the reset
- the posture the refactor should take

## Invariants

- The refactor is not a rejection of the platform's strongest ideas.
- State-machine thinking, progressive-disclosure context engineering, and
  AI-first product direction are assets to preserve.
- The daemon must not remain the gravity well for local bookkeeping and broad
  business logic.
- The API must remain a transport boundary, not a domain owner.
- The redesign must be top-down and ownership-first, not a patch series against
  the current monolith shape.

## Primary flows

### What is worth preserving

TeleClaude has already produced several unusually strong ideas. These should be
treated as assets to preserve, not as legacy baggage to throw away.

### 1. Workflow/state-machine thinking

The system models work as explicit state transitions rather than loose command
sequences. That is a major strength and should remain central.

### 2. Progressive-disclosure context engineering

The current context approach is better than naive RAG:

- layered scopes,
- policy-driven selection,
- memory injection,
- context narrowing,
- purposeful delivery instead of retrieval spam.

That philosophy should survive intact.

### 3. Operationally useful abstractions

The platform already contains valuable abstractions for:

- session runtime,
- adapter boundaries,
- workflow orchestration,
- background processing,
- durable receipts and state transitions.

These are signs of a strong architectural instinct, even if the current
implementation has drifted.

### 4. AI-first product direction

The platform is already close to an AI-native small-business operating system.
That direction is sound. The refactor is about making the base worthy of the
ambition.

### What drifted

The core problem is not that the platform grew. The problem is that ownership
blurred over time.

### 1. The daemon grew into a gravity well

The daemon gradually became the execution path for concerns it should not own:

- local bookkeeping,
- transport-driven business logic,
- broad cache invalidation responsibilities,
- startup-critical side work,
- authentication pressure that belongs at boundaries.

This made the daemon heavier, slower to restart, and harder to reason about.

### 2. The API became more than transport

Routes and daemon-backed handlers started to define behavior rather than merely
expose it. Once that happened, CLI/API concerns and domain concerns became
entangled.

### 3. CLI lost local autonomy

The intended architectural promise was that project-local work could continue
when runtime services were down. In practice, too many CLI bookkeeping flows now
go through daemon API paths. That is a direct violation of the intended model.

### 4. Storage truth fragmented

Operational truth became split across:

- files,
- SQLite tables,
- transcript parsing,
- mirrors,
- caches,
- ad hoc registries.

This created duplication, repair loops, and fragile consumers.

### 5. Startup/shutdown boundaries blurred

Too many things now start together, restart together, and fail together:

- daemon runtime,
- API availability,
- helper watchers,
- projection/repair work,
- optional subsystem imports.

This made restart pain much worse than it should be.

### Symptoms that exposed the drift

Recent investigations made the drift visible in concrete ways.

### 1. Local todo operations were not truly local

`telec todo` paths still route through daemon-backed API calls in places where
they should use local services directly.

### 2. Logical operations were stitched from multiple writes

Multi-step workflow mutations were split into separate commits instead of one
transactional domain operation. This introduced lock contention and correctness
risk.

### 3. Transcript consumers multiplied

Too many consumers treated raw transcript format as a usable read model. Mirrors
and transcript scans became compensating mechanisms instead of clean
architecture.

### 4. Watchers and helpers became host-level operational debt

Per-project services, leftover helpers, and unsafe runtime behavior created
unnecessary machine-level instability.

### The architectural reset

Architecture V2 is not a rejection of the platform. It is a clarification of
what the platform was trying to become all along.

The reset is:

- local-first where work must remain autonomous,
- event-driven where side effects must be restart-safe,
- domain-first where business logic must stay coherent,
- storage-first where operational truth must be durable and typed,
- thin at the boundaries where transports should not own behavior.

### What this means in practice

### Keep

- state machines,
- progressive disclosure,
- strong workflow thinking,
- runtime session orchestration as its own concern,
- AI-first product ambition.

### Change

- daemon scope,
- API scope,
- CLI coupling,
- storage truth,
- projection model,
- restart boundaries.

### Remove

- business logic embedded in transports,
- daemon ownership of local bookkeeping,
- transcript-parsing as a consumer contract,
- file-sprawl as operational truth.

### Refactor posture

The right posture is not “patch the monolith forever,” and not “throw away all
the good ideas.”

It is:

- preserve the beautiful ideas,
- extract the real bounded contexts,
- rebuild the platform around clean ownership,
- and migrate deliberately with strong invariants.

### Decision

Architecture V2 should be treated as a top-down redesign of the platform shape,
followed by bounded-context implementation plans and ordered refactor todos.

The goal is not just a cleaner codebase.

The goal is a sane, scalable, AI-native platform that can support the next phase
of product growth without dragging all concerns through one tangled runtime core.

## Failure modes

- Treating the refactor as a rejection of everything already built and throwing
  away the platform's strongest ideas.
- Treating the refactor as a patch-only exercise and leaving daemon/API
  overreach intact.
- Preserving implementation details instead of preserving the real design wins.
- Rebuilding around runtime concerns first and reproducing the same gravity well.
- Letting storage truth remain fragmented across files, transcript parsing, and
  ad hoc caches.
