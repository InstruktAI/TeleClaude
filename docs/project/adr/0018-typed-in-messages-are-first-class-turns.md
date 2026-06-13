---
date: '2026-06-08'
description: 'Typed-in input, whether human or inter-actor, defines a real session turn; only hook side-channel artifacts are excluded from turn boundaries and notification dedup resets.'
number: '18'
visibility: 'public'
---

# Typed-In Messages Are First-Class Turns — ADR

## Context

Stop notifications can be lost after an orchestrator re-pokes a worker with
`telec sessions send`. The worker's stop fan-out is gated by a per-target
notification dedup flag that is set after a successful stop notification and
cleared on the next real input turn.

The hook receiver previously classified orchestrator, integrator, peer, system,
and TeleClaude notification/input-request/linked-output envelopes as
system-injected prompt text. Those `user_prompt_submit` events were dropped at the
receiver before reaching the daemon, so the coordinator never cleared the dedup
flag or set a new turn anchor. The next worker stop then looked like a duplicate
stop in the same turn and the caller was not notified.

## Decision

The turn boundary is defined by typed-in input. Human text and inter-actor
messages typed into a session are first-class turns: orchestrator, integrator,
peer, system dispatches, and TeleClaude Notification / Input Request / Linked
output envelopes all count.

Only hook side-channel artifacts are excluded from turn boundaries: checkpoint
Stop-hook feedback and CLI-internal wrappers such as `<system-reminder>`,
`<task-notification>`, `<hook_prompt>`, `Stop hook feedback:`, and
`PreToolUse hook feedback:`. A single shared predicate owns that non-turn set and
is consumed by the hook receiver gate and transcript turn detection. Direct
conversation delivery uses a narrower loop guard: only TeleClaude peer-bridge
messages are withheld from cross-delivery to prevent A-to-B-to-A echoes.

## Consequences

Inter-actor messages now clear the per-target stop-notification dedup flag, set
the turn anchor, and participate in transcript turn-boundary detection. A worker
re-poked by an orchestrator can notify the caller again on the next completed
turn, still with one stop notification per completed turn.

Hook side-channel artifacts remain non-turns and do not clear the dedup flag, so
checkpoint and CLI runtime feedback cannot create duplicate stop notifications.

Cross-delivery becomes bridge-only for loop prevention. Peer-bridge blocks are
excluded from bundles, while orchestrator/integrator/system content typed into a
linked session can cross-deliver as real conversation content.
