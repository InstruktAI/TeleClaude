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

<!-- planned:issue-128 -->

- The port supplies each act as one coherent logical act together with the
  artifact revisions it was decided on (#124 INV-S3).
  - **Local adapter.** It commits the act in one atomic SQL transaction and
    rolls the whole act back on failure.
  - **GitHub adapter.** It supplies observed-revision validation: the act records
    the revisions it observed and checked, and an observed mismatch refuses the
    act. This is not a cross-object commit-instant fence. Publishing the act
    neither locks nor overwrites a concurrent body edit.
  - **Unconfirmed provider acceptance.** It is a separate recovery outcome and
    supplies no committed-act evidence.

<!-- /planned:issue-128 -->

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

### Store activation

<!-- planned:issue-128 -->

The local adapter keeps one completion mark per store, in the store (a table the existing schema migration creates), recorded only by the activation, after the legacy import has completed, every row is classified and a verification pass has found nothing left to convert. The activation is a step of the daemon's per-project minute pass, run before the pass reconciles effects, for every checkout the computer lists. Nothing records a machine-wide completion, so a store registered, created or restored later is activated by the next pass, a store whose activation fails stays unmarked and is refused with the cause while every other store proceeds, and no version range or applied-identifier set decides whether a store is activated. The generic bootstrap and every read path stay non-mutating for data, and worktree or command-line openers never activate.

For one store the activation is all or nothing in one write transaction: (a) before it, complete the legacy markdown import and read the checkpoint; (b) inside it, establish the converted-row table and the enforcement of its two predicates and verify them; (c) reread the checkpoint, and classify every row of a kind other than task in this order, the first match deciding: (1) the row already records an admission (the admission write precedes the checkpoint's publication of it, so activation can run between the two): keep that admission, and when the record is stored in a legacy phase and its creative state is not complete, open its creative episode as a deferred conversion, changing neither its stored phase nor its holder; (2) no row admission, and the checkpoint names the row in an active, non-idle state: record the row's admission from that exact identity (item, branch, commit) and handle its creative episode as in (1); a checkpoint candidate whose identity differs from a recorded row admission is a conflict, and the store is refused as not activated naming it; (3a) neither, and the record is stored in a legacy phase with a complete creative state and no creative episode ever opened for it: normalize it forward with its reading unchanged (a carried finalize handoff or a review verdict at the head becomes a stored `ready` with a stamp at that commit and time whose typed source is the carried handoff or verdict and whose acting session is empty, the carried reviewer staying legacy provenance (a verdict whose head cannot be read is left for a later pass, and a record that a retired kickback or drift flag keeps out of candidacy mints no stamp and becomes `preparation`); every other legacy phase becomes `preparation`), changing no other recorded fact, raising no ready event, and insert its converted-row record; (3) neither, and the record is stored in a legacy phase with an incomplete creative state: replace its stored phase with `preparation`, open its creative episode, write the canonical latest payload, and insert the row's converted-row record, preserving a queued or parked checkpoint entry and key. A deferred row counts as classified, not as an unconverted failure, for the completion mark; the pass that first finds it without an admission completes its conversion; a delivery wins over every one of these; (d) verify nothing is left to convert and record the mark, which leaves no legacy stored value except an actively admitted attempt, converted by the first pass that finds it without an admission, persisting `preparation` and keeping the episode whether its creative state is still incomplete or has since completed, and a `review_approved` verdict whose integration head could not be read, which activation counts as classified and the first later pass that can read the head completes; (e) commit. A failure rolls the whole store back.

**The converted-row record and its enforced predicates.** A table holds one record per converted row (row id as key and foreign key with delete cascade, the replaced phase, the time and the path `activation`, `restore` or `capability`), inserted in the same transaction as the conversion it records and never updated or deleted by the machine; it is history and not an open episode. The store refuses, for a converted row, any update whose new state lacks the structured workflow record or whose phase is not a phase of the machine (`preparation`, `waiting`, `work`, `ready`, `delivered`, `prepared` carrying the prepared record, or, for kind task, a task-lane phase), and the refusal names its door: read the item again and write from the current state. These two predicates are the contract; the store's implementation owns how they are enforced, whichever writer or code version attempts the update. The kind change of a converted row stores `preparation` for a non-task target and the task lane's entry phase for a task target. A store is marked activated only while the record table and the enforcement of the two predicates are in place, and the machine's reads check the mark and both.

A compatibility upgrade preserves concurrent state changes and satisfies the same converted-row predicates as every other writer; an upgrade whose precondition no longer holds writes nothing.
<!-- /planned:issue-128 -->

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
