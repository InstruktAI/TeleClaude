---
description: Backend-neutral port and local adapter boundary for workflow records, operations, and integration.
visibility: internal
delivered_by:
  - issue-126
---

# Workflow Store — Design

## Purpose

Give workflow consumers one typed, backend-neutral operation surface. The
project resolver selects the adapter once for the canonical shared-state root.
Local remains the default and is the only implemented adapter in this slice;
explicit `todos.store: github` fails with an unavailable-capability error.
Consumers do not select a backend, open a connection, inspect tables, or carry
storage paths.

## Required reads

- `local/projects/teleclaude/spec/domain/workflow`
- `local/projects/teleclaude/spec/feature/workflow/todo-management`
- `local/projects/teleclaude/spec/feature/workflow/todo-removal`
- `local/projects/teleclaude/spec/feature/workflow/todo-state-transfer`
- `local/projects/teleclaude/spec/integration-orchestrator`
- `sdlc/principle/design-fundamentals`

## Inputs/Outputs

The public identity `WorkItemId` is the canonical slug. A separate opaque
`StoreAddress` carries adapter-local addressing needed for operations that are
currently row-UUID addressed. Neither value substitutes for the other. Typed
records include `WorkItem`, `WorkItemQuery`, `Dependency`, `ClaimHolder`,
`GroupMembership`, `PhaseState`, `ArtifactBody`, `ArtifactVersion`,
`ArtifactDiff`, `Stamp`, `TrailNote`, `DeliveryLink`, `ReadyCandidate`,
`StorePresence`, and `StoreCapabilities`. Existing task, schedule and creative
state remain within workflow state and preserve their current ownership and
interpretation.

The operation contract has seven parts:

- **Items:** create, read, list, edit intent body and close; typed projection
  includes metadata, grouping and dependency facts.
- **Claims:** claim, release and read the live session holder. Structural group
  membership and `status=holder` are distinct item facts; they are not claim
  ownership.
- **Phases:** read canonical phase and advance through the existing validated
  transition boundary.
- **Stamps:** add and read verdicts bound to the current artifact digest or
  commit SHA.
- **Notes:** append and read identity-attributed workflow trail records.
- **Delivery:** link branch/PR, enumerate ready candidates and record delivery
  against the confirmed final root SHA.
- **Capabilities:** report adapter operations and refuse an unavailable
  capability explicitly.

## Invariants

- One cache identity is keyed by the canonical shared-state root. A linked
  worktree and its owning checkout resolve to the same adapter. Sync and async
  facades share this identity and event-hook attachment; sync calls stay native
  sync and do not invoke a nested event loop.
- Adapter commands retain existing transaction boundaries and callback
  multiplicity. Artifact content and version append commit together and notify;
  provenance state is a later, separate commit and notification. A failure
  between those commits remains observable as it is today. Delivery and later
  dependency cleanup likewise retain their source-defined boundaries.
- A phase mutation persists before its existing transition notification. Failed
  persistence emits no successful transition. Hook registration occurs once
  per cached adapter.
- Local slug identity, row UUID addressing, live claims, structural group
  holders, transitive claiming-group authorization and role checks remain
  separate facts. SHA/digest-bound stamps, audit, attribution and timestamps
  retain their existing meaning.
- Validation reads distinguish absent storage from invalid state and never
  bootstrap or migrate. SQL and compatibility with legacy local tables remain
  inside the local adapter.
- Existing computer-target transfer stays incremental and daemon-independent,
  including its running-target support, integrity checks and existing admin and
  role clearance. The adapter supplies an opaque transfer operation; callers
  do not receive a database path or SQL connection.
- Integrator candidate selection preserves current eligibility, FIFO ready
  ordering, dependency exclusion, durable checkpoint, lease and parking
  behavior, duplicate-integration guards and final-root confirmation. Delivery
  is recorded once at the confirmed final root SHA.

## Primary flows

1. Resolve project context to the canonical state root, read its project config,
   select the store, and refuse before storage access when the selected
   capability is unavailable.
2. Consumer invokes one typed workflow operation. The adapter maps canonical
   slugs and optional row-address tokens to local storage and owns all SQL,
   migrations, sessions and result translation.
3. Local async daemon paths and native sync CLI/integrator paths use the same
   cached store identity. Successful mutations preserve existing callbacks and
   downstream cache/event behavior.
4. Validation and transfer use explicit adapter operations that preserve their
   no-bootstrap or daemon-independent boundaries.

## Failure modes

- A missing store is a distinct read result from a malformed database or state
  record. Validation cannot create storage to make its read succeed.
- Adapter selection fails before local bootstrap when the selected adapter is
  unavailable; it does not silently fall back to local.
- A failed mutation retains the existing commit boundary and refusal. The
  adapter does not synthesize defaults, retry a failed write as success, or
  collapse distinct current commits.
- A transfer source is opaque. Exposing a local path would recreate the direct
  storage bypass this boundary owns.

## See Also

- docs/local/spec/domain/workflow.md
- docs/local/spec/feature/workflow/todo-state-transfer.md
- docs/local/spec/integration-orchestrator.md
