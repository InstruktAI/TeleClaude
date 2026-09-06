---
description: Persistent listener registry and parent-attention delivery with source provenance, terminal-outcome slots, and cross-computer audience resolution.
visibility: public
---

# Session Listeners — Design

## Required reads

@docs/project/spec/session-subscriptions.md
@docs/project/spec/feature/agent_runtime/session-subscriptions.md
@docs/project/spec/feature/agent_runtime/control-delivery.md

## Purpose

The agent-runtime listener service owns passive caller-target interest and
routes observations to that audience. Direct conversation links own a separate
state plane. Their interaction follows the subscription specs above.

## Inputs/Outputs

Inputs are registration, unsubscribe and cleanup requests; normalized native
observations; turn completions; and addressed observations forwarded from
another computer. Provider adapters own native event names and their mapping
to the shared event vocabulary.

Outputs are durable listener records, semantic notification envelopes handed
to control delivery, and delivery results. Known distress with no reached
watcher uses the target session's existing human-facing output lane. Neutral
native notifications have no human-facing fallback.

An attention observation carries target identity and locality, originating
runtime, native kind and available subtype/details, source-occurrence identity,
and observation time with its provenance. A receiver timestamp identifies when
TeleClaude observed the event; it does not claim to be the provider's event time.
Missing native information remains explicitly unavailable.

## Invariants

- Listener state is durable and unique per caller-target pair. Registration
  preserves an existing row's subscription mode.
- Dispatch registers persistent interest; a non-direct message can register
  single-reply interest. Unsubscribe and session cleanup own row removal.
- Only turn-end delivery consumes a single-reply subscription. Native attention
  addresses persistent listeners and any declared remote initiator.
- Direct-link suppression applies to turn-end only. Blocked, failed and neutral
  notification observations are not withheld by a direct conversation link.
- Turn-end and turn-failure contend for one terminal-outcome slot per turn.
  A later terminal signal does not replace the first account. The next accepted
  real user entry clears the slot; hook-side feedback does not.
- Nonterminal attention bypasses turn/kind suppression. Separate occurrences
  retain their source identity through control delivery, even within one turn
  or while the same condition remains unresolved.
- Listener fan-out adds no duplicate detection, coalescing, acknowledgement,
  retry, or processing-confirmation state. Control delivery owns the handoff.
- The source computer resolves the persistent audience and known-distress
  fallback. A remote recipient receives an already-addressed observation and
  returns whether its handoff was accepted; it does not reconstruct the source
  computer's audience or select a fallback.
- A watcher is reached when control delivery accepts the handoff, not merely
  because its listener row exists. Known distress falls back only when no local
  or remote audience member is reached.
- Native text is evidence within the platform-authored attention message. It
  is visibly identified as provider-supplied data and is never an identity
  header, permission grant, recovery decision or executable instruction.
- The emitting child's observation hook grants no context-injection capability.
  Parent delivery uses that recipient's eligible hooks and existing composer
  protection through control delivery.

## Primary flows

### Registration and lifecycle

Session creation registers persistent caller-target interest. A non-direct
message registers single-reply interest when no row already exists. Direct-link
creation and severance leave listener rows intact. Unsubscribe removes the
caller's listener and closes its direct link independently. Ending a target
removes its incoming listeners; ending a caller removes its outgoing listeners.

### Terminal completion

The coordinator claims the terminal-outcome slot, resolves listeners and checks
each caller-target direct link. Unsuppressed turn-end notifications are handed
to control delivery. Their single-reply listener is spent after the delivery
attempt, including a refused attempt. Persistent listeners remain registered.

### Native attention

The provider adapter normalizes each native observation once. Known failure
claims the terminal-outcome slot; blocked and neutral observations bypass it.
The coordinator supplies the observation to the listener service, which
attempts its persistent audience through the existing control handoff. The
origin includes the addressed remote initiator in that audience. Only known
distress with no accepted audience member reaches the target's output lane.

### Parent assessment

The platform-authored message identifies the observation and directs the parent
to inspect current state and recover within its existing mandate. It carries an
actionable terminal-inspection route from the session-transcript-retrieval
contract. Transcript tailing remains contextual evidence; unchanged transcript
output does not establish an unchanged terminal. A computer selector appears
on every suggested command only when the target is remote.

### Stale-listener inspection

The registry exposes stale targets for inspection and advances their inspection
timestamps. This query changes neither subscriptions nor session lifecycle;
the inspecting agent owns any subsequent action.

## Failure modes

- A stale persistent listener can refuse delivery; its row remains and it does
  not suppress the known-distress fallback.
- A remote forward reports its delivery result to the origin. Failure cannot
  be counted as a reached watcher.
- A neutral notification with no reached watcher has no human destination.
- Known distress with neither a reached watcher nor an available target output
  lane is reported undeliverable; no other audience is selected.
- Attention may already be obsolete when read. The parent assesses fresh state
  before acting; the observation itself changes no authority.
- A provider without a native hook for an observation produces none. Silence
  is not a synthesized failure or completion.

## See Also

- docs/project/spec/feature/agent_runtime/session-transcript-retrieval.md
- docs/project/spec/hook-normalized-events.md
- docs/project/spec/event-vocabulary.md
- ~/.teleclaude/docs/general/principle/intelligence-boundaries.md
- ~/.teleclaude/docs/general/policy/human-contract.md
- ~/.teleclaude/docs/software-development/policy/domain-ownership.md
