---
description: 'Receipt-first contract for asynchronous work: immediate operation_id, durable row, background execution, distinct outcome events, and delivery to the caller that asked.'
visibility: 'public'
---

# Operation Receipts — Design

## Required reads

- @docs/local/design/architecture/command-classification.md

## Purpose

A command whose work finishes after its response uses the receipt-first contract. The
daemon persists an operation row before execution begins, returns a durable
`OperationReceipt` immediately, and runs the work in a tracked background task. On the
terminal transition it emits the command's success or failure event and wakes the caller
recorded on the row.

This is the only asynchronous contract. A mutation fast enough to answer inside its own
response is `IMMEDIATE` and carries no operation row; everything else carries one. There
is no lighter asynchronous form, because an outcome with no row cannot be answered for
after the fact.

### Operation kinds inventory

Each operation kind is declared once, with the success and failure events its
terminal transition emits, in `teleclaude/core/operations/_kinds.py`; the
route that submits it calls the matching submission method of the operations
service (`teleclaude/core/operations/service.py`). Those declarations are the
inventory.

## Inputs/Outputs

- **Input:** Any route backed by a RECEIPT command, carrying the caller provenance the
  API boundary resolved and, for a session-scoped command, the computer that owns the
  target.
- **Output (immediate):** `OperationReceipt` — `{operation_id, kind, state: "queued",
status_path, poll_after_ms, computer, success_event, failure_event, recovery_command}`.
- **Output (terminal):** `GET /operations/{operation_id}` returns the full receipt with
  `state: "completed"|"failed"|"stale"` and `result` or `error`.
- **Output (delivery):** the caller recorded on the row is woken with an address —
  operation identity, outcome, and the command that reads the record.
- Operation rows are keyed to the caller session and record the subject the operation runs in —
  the subject of its working folder, or of the session it acts on — with that subject's owner as
  resolved when the operation is created. A row written before operations recorded a subject
  receives once the subject and owner of its working folder or target session; a row whose
  subject cannot be established records it as unknown, which only platform reach and its own
  caller see. A caller may inspect its own,
  and any operation whose subject its reach admits
  (`local/projects/teleclaude/spec/feature/identity/data-visibility`). A read from another computer
  carries no session (`local/projects/teleclaude/spec/feature/identity/cross-computer-authorization`),
  so there a caller's own operation is one whose command the caller's principal started.

## Invariants

### Published work feedback

An operation retains its semantic owner's optional work-feedback declaration
separately from its result and diagnostic error. The declaration is persisted
in the same terminal write and projected identically by operation status reads
and authorized live outcome delivery. A completed operation may carry a work
refusal; completion alone does not grant notification eligibility.

The operation carrier transports the declaration without deriving it from
result prose, error prose, exception ancestry or HTTP status. Presentation
applies the work-feedback boundary
(`local/projects/teleclaude/spec/feature/presentation/work-feedback`); operation
state, terminal event types and caller wake delivery keep their own contracts.

Existing operation records acquire an absent declaration through the storage
migration. A wire payload without the optional declaration supplies no work
feedback; a consumer does not reconstruct one from its diagnostic fields.
External shape evolution preserves independent consumers
(`sdlc/policy/backward-compatibility-hygiene`).

- **Persist before execute.** The operation row is written to DB before the background
  task is scheduled. The receipt is always valid even if the daemon crashes immediately
  after returning it.
- **Submit dedupe.** `client_request_id` scoped by operation kind and caller session
  prevents duplicate executions. Re-submitting with the same `client_request_id`
  reattaches to a matching nonterminal operation row.
- **The caller is recorded at submission.** The row carries the caller provenance the
  command arrived with. A caller-less submission is recorded as such; nothing is inferred
  to fill the gap.
- **Atomic terminal transition.** The background task emits the outcome event as the
  final step of writing the terminal DB state. The event and the row transition happen
  in the same logical unit — never split.
- **Outcome is carried by event type.** A terminal transition emits the command's
  `success_event` or its `failure_event`. No consumer distinguishes outcomes by reading a
  field on a shared event type.
- **Every terminal transition delivers.** Completion, failure, and staleness each reach
  the recorded caller if it is still live. Staleness is an outcome, not an absence of one,
  so a daemon restart is observable to the caller rather than silent.
- **Delivery carries an address, never the record.** The wake names the operation, its
  outcome, and where to read it. The row supplies the result, the error, and the progress
  detail when the caller reads it.
- **Delivery failure is terminal and harmless.** A wake that cannot be handed off is not
  retried. The row is unaffected and answers whoever asks later.
- **Stale on restart.** Operations in `queued` or `running` state are marked `stale`
  at daemon startup. Work is never replayed blindly. The receipt remains truthful.
- **The row is the authority.** Outcome events are a nudge toward the row, never the
  record. If an event fires but the row is not yet terminal, trust the row.
- **The owning computer owns the row.** An operation submitted on behalf of a caller
  elsewhere is persisted, executed, and emitted by the computer that runs the work. The
  receipt names that computer so the caller reads the record there.

<!-- planned:issue-129 -->

### Remote posting caller continuity

Receipt-backed GitHub work stores the admitted caller principal as nullable
`caller_principal` in the operation row beside its caller computer and session,
sourced from request-scoped identity context before the task is scheduled.
`caller_provenance_json` remains attribution projection and is not authority.
Existing rows migrate with an absent principal;
an absent legacy principal supplies no remote GitHub authority, while unrelated
operation reads and behavior remain unchanged.

Client-request deduplication, nonterminal reattachment, and a uniqueness-race
reread each require the admitted principal, origin computer, and origin session
to match the recorded row before returning its receipt or scheduling work.
Missing or conflicting facts refuse; reattachment never replaces the original
caller. The runner restores and resets the principal with the existing session
and locality tokens in `operation_caller_identity`. Existing stale-on-restart and no-automatic-replay semantics
remain. An immediate act remains `IMMEDIATE` with no row; its source invocation
identity comes from the act owner, never from an invented operation ID.
<!-- /planned:issue-129 -->

## Primary flows

1. A route receives a RECEIPT command and calls `OperationsService.submit(command)` with
   the caller provenance the command carries.
2. `OperationsService` deduplicates via `client_request_id`, persists the row
   (`state=queued`, caller recorded), and returns the receipt immediately.
3. A background task claims the queued row (`state=running`), heartbeats periodically,
   and executes the work.
4. On the terminal transition, the task writes the result to the row and emits the
   command's success or failure event.
5. The recorded caller, if still live, is woken through control delivery with an address.
   A caller on another computer is reached by forwarding the notification to that
   computer, which delivers it locally.

6. The caller reads `GET /operations/{operation_id}` for the full record. The command
   line never waits for the terminal state; it returns the receipt, and the wake is how
   the caller learns the operation has finished.

```mermaid
sequenceDiagram
    participant Caller
    participant OperationsService
    participant DB
    participant EventBus
    participant Delivery as Control delivery

    Caller->>OperationsService: submit(command, caller)
    OperationsService->>DB: persist row (queued, caller)
    OperationsService->>Caller: OperationReceipt
    OperationsService->>DB: claim (running) + heartbeat
    OperationsService->>DB: terminal row (completed | failed | stale)
    OperationsService->>EventBus: success_event | failure_event
    OperationsService->>Delivery: wake the recorded caller
    Delivery->>Caller: address (operation id, outcome, where to read)
    Caller->>DB: GET /operations/{id}
```

## Failure modes

- **Daemon restart:** Leftover `queued` or `running` operations are marked `stale`
  at startup. That transition emits the failure event and wakes the recorded caller, so a
  caller that was waiting learns the work was abandoned rather than waiting out a timeout.
  Work is never replayed automatically.
- **Background task panic:** If the task dies before the terminal write, the row stays
  `running` until the heartbeat window expires and then becomes `stale`, which delivers.
- **Caller session gone at delivery:** The wake is dropped without retry and the row is
  unchanged. The outcome remains answerable by any later reader.
- **Caller mismatch:** A caller whose reach does not admit the operation's subject, attempting
  to access an operation that is not its own, receives a 404 (not a 403) to avoid session ID
  enumeration.
- **Event fires, row not yet terminal:** Trust the row. The event is a convenience
  signal; the DB row is authoritative.

## See Also

- docs/local/adr/0098-async-work-always-carries-a-receipt.md
- docs/local/adr/0119-the-cli-never-waits-on-a-receipt.md
- docs/local/spec/feature/agent_runtime/control-delivery.md
