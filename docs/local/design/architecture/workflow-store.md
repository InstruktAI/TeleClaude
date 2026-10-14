---
description: Backend-neutral port and local adapter boundary for workflow records,
  operations, and integration.
visibility: internal
---

# Workflow Store — Design

## Required reads

- @docs/local/spec/domain/workflow.md
- @docs/local/spec/feature/workflow/todo-management.md
- @docs/local/spec/feature/workflow/todo-removal.md
- @docs/local/spec/feature/workflow/todo-state-transfer.md
- @docs/local/spec/integration-orchestrator.md
- @~/.teleclaude/docs/sdlc/principle/design-fundamentals.md

## Purpose

Give workflow consumers one typed, backend-neutral operation surface. The
project resolver selects the adapter once for the canonical shared-state root.
Local remains the default and is the only implemented adapter in this slice;
explicit `todos.store: github` fails with an unavailable-capability error.
Consumers do not select a backend, open a connection, inspect tables, or carry
storage paths.

## Inputs/Outputs

The canonical item identity is its slug. The typed projection uses
`WorkItemId` for that identity and a separate opaque `StoreAddress` for local
row addressing; neither substitutes for the other. Existing protocol methods
retain slug and row-id string parameters where current consumers use them, and
the adapter resolves the local address. The operation records currently used
by `WorkflowStore` are `WorkItem`, `TodoDiagnosticRecord`,
`WorkItemStateRead`, `IdentityResolution`, `RemovalRequest`,
`ExpiredRemovedItem`, `PurgedItem`, `ArtifactMetadata`, `ArtifactWriterSet`,
`ArtifactRemoval`, `ArtifactVersion`, `StoreCapabilities`, and
`TodoProjectionSnapshot` with `TodoProjectionItem`, `TodoProjectionMetrics`,
and `ArtifactFile`. Dependency operations use `DependencyEntry`; workflow
state remains `dict[str, StateValue]`. The selected-store helpers additionally
use `StorePresence`, `StoreIntegrityStatus`, and the opaque `TransferSource` /
`TransferResult` pair. Existing task, schedule and creative state remain within
workflow state and preserve their current ownership and interpretation.

The seven operation parts are realized by the current state and artifact
operations:

- **Items:** `add_to_todo`, `list_todo`, `read_todo_diagnostic_record`,
  state/artifact reads and writes, soft removal/reactivation, and the typed
  projection cover create, read, list, intent-body edit, close and metadata.
  Slug identity and row addressing remain distinct.
- **Claims:** `active_runner` is read and written as workflow state; lifecycle
  code applies the existing session-liveness and caller-ownership checks around
  that state. Structural group membership and `status=holder` use separate
  operations and remain distinct facts.
- **Phases:** validated phase state is read and written through workflow state;
  `freeze`, `unfreeze`, `deliver`, and the registered transition hooks preserve
  existing phase and notification boundaries.
- **Stamps:** verdict state is bound to `artifact_digest` or commit SHA. The
  artifact-version reads and `update_state_with_artifact_evidence` provide the
  revision evidence while preserving the current mutation boundary.
- **Notes:** the local trail is the versioned `log` artifact, read and written
  through artifact operations. `artifact_versions` and writer metadata retain
  the existing trail and attribution behavior.
- **Delivery:** the typed projection and dependency reads feed existing ready
  candidate selection; `deliver` / `deliver_sync` record the confirmed root
  SHA, and downstream dependency cleanup remains a separate operation.
- **Capabilities:** `WorkflowStore.capabilities` reports the local adapter's
  supported operations; selecting unavailable GitHub refuses before local
  storage access.

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
