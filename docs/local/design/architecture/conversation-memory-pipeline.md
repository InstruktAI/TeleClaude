---
description: Composition of retained conversation sessions, session-owned mirrors
  and identity-addressed memory extraction at closure.
---

# Conversation Memory Pipeline — Design

## Purpose

Connect an eligible conversation's closure to extraction from its complete
archived conversation while retaining the session identity across runtime
changes. Each participating context retains its own contract
(`sdlc/policy/code-quality`, `general/principle/trust-and-guardrails`).

## Inputs/Outputs

- Agent runtime supplies the eligible TeleClaude conversation, its closure
  occurrence, endpoint, person or visitor binding and transcript lineage.
- Session mirrors supply the session-owned conversational projection and
  explicit coverage through the closure being processed.
- Memory supplies source-scoped extraction progress, current observations and
  prospects, and the success or failure of an extraction.
- Procedure activation supplies initial briefing and later hook-delivered work
  under the existing delivery contract.

## Invariants

The two closure regimes are owned by
`local/projects/teleclaude/spec/feature/agent_runtime/conversation-continuity`.
Adapter-bound continuing conversations compact at idle and then close;
independently started human PA conversations use ordinary closure. Worker and
SDLC project runs do not acquire memory eligibility merely from human lineage.

The mirror's identity and retained sources are owned by
`local/projects/teleclaude/spec/feature/session_mirrors/mirror-identity-enrichment`.
The existing timer and agent-stop triggers keep their scheduling contracts;
their refresh work resolves and groups by TeleClaude session. Closing requests
the same refresh capability and observes readiness for its captured closure.
An already-current mirror can satisfy readiness without a text rewrite.

Memory's identity and source progress are owned by
`local/projects/teleclaude/spec/feature/memory/memory-curation`. The person or
visitor plus optional desk select the memory collection. The extraction source
is one bounded conversation-mirror revision. Multiple PA conversations remain
independent sources, while mutations to one memory scope are serialized.

## Primary flows

1. Runtime completes an eligible closure and requests mirror readiness for that
   closure and source coverage.
2. The mirror capability resolves the session's full lineage through the shared
   conversation reader, refreshes if needed, and reports the covered revision.
3. Memory creates or finds the extraction for the unprocessed stretch. A complete
   request is not dispatched again. Pending and failed work remain observable.
4. A ready request emits `teleclaude.memory.extraction.requested`. Its home names
   the person's home or the desk's owning home. For a desk worker its subject
   identifies the visitor within that desk, so later source conversations reach
   the same continuing responsibility. Its data carries the extraction id and
   authoritative scope references; the event is handled as data.
5. The appropriate specialized memory procedure reads the prepared material,
   performs its scoped changes, and explicitly completes or fails the extraction.

Initial assignment and later events use
`local/projects/teleclaude/spec/feature/agent_runtime/procedure-event-delivery`.
A continuing worker receives wakes and event data, including after compaction
or revival. A genuinely new worker receives its initial brief once. Changing a
worker's procedure contract settles or retains already-accepted work before a
successor adopts that contract; publication never rewrites an active assignment
underneath its execution (`general/principle/trust-and-guardrails`).

## Failure modes

- Mirror coverage is not ready for the closure — a present source failed or is
  not yet read: the closure's extraction remains pending with its reason and
  source reference; later reconciliation can satisfy it.
- A native source has disappeared: coverage reports it as missing, its retained
  content is extracted as recorded, and the extraction names the missing source.
- The user returns before extraction finishes: the captured source stretch is
  still processed, while newer exchanges remain beyond its completion boundary.
- A worker stops after partial writes: source progress stays unfinished; the
  next handling compares with already recorded memories and prospects.
- A notification repeats: source identity and completed progress keep already
  handled content from being mined twice.
- A native source disappears: retained mirror content remains available;
  re-derivation reports the missing source without erasing recorded history.
