---
description: 'Restart-safe peer conversation replay built from transcript truth and directional delivery cursors.'
visibility: 'public'
---

# Conversation Delivery — Design

## Required reads

- @docs/project/spec/session-subscriptions.md

## Purpose

Keep direct conversations correct across normal turns, human interjections, and daemon restarts.

This system owns the direct-link axis of the subscription model. It is independent of the listener axis (see `session-listeners`). The cross-axis contract — including the link-aware suppression rule that gates listener notifications while a link is active — is canonical in `session-subscriptions`.

- Conversation links persist membership in the database.
- Session state stores the last TeleClaude conversation injection timestamp.
- Directional delivery state stores what each peer has already received from each source.
- Transcript files remain the source of truth for what was actually said.

## Inputs/Outputs

**Inputs:**

- Active conversation links and link members from the database
- Source session fields:
  - `last_conversation_injected_at`
  - `native_log_file`
  - `active_agent`
- Directional delivery cursor rows from `conversation_delivery_state`
- Transcript projection via `project_entries(..., WEB_POLICY, since=...)`
- Stop-time wakeups from `agent_stop`
- Startup wakeup from daemon lifecycle reconciliation

**Outputs:**

- A single mirrored bundle per delivery, framed as
  `[TeleClaude Conversation update from ...]`, whose body contains one inner
  marker per source segment in temporal order:
  `--- Human in the Loop @ <iso8601> ---` for visible user turns and
  `--- Linked output @ <iso8601> ---` for assistant turns.
- Advanced directional delivery cursors after successful durable handoff.

## Invariants

- **Transcript truth**: replay is computed from transcript content, not from hook payload bodies.
- **Session-local anchor**: `last_conversation_injected_at` marks the most recent TeleClaude conversation injection into a session.
- **Directional progress**: delivery is tracked per `(link_id, source_session_id, target_session_id)`.
- **Boundary is later(anchor, cursor)**: replay starts at the later of the session anchor and the persisted directional cursor.
- **Per-link cursor seeded at link creation**: when a fresh direct link is created, both directional cursors (`caller→target` and `target→caller`) are seeded with `now()` as `delivered_through_ts`. Without this floor, the sender side has no anchor refresh from the Direct Conversation intro (only the receiver does), so a stale `last_conversation_injected_at` from a prior link or fan-out would pull pre-link transcript content into the first bundle. The cursor floor is per-link and authoritative regardless of session-level anchor history. Reused links keep their existing cursors.
- **Visible content only**: replay includes visible `user` and `assistant` text blocks. Agent-CLI runtime artifacts (`<system-reminder>`, `<task-notification>`, hook-feedback prefixes) are stripped by the projector. Bracket-marked machine messages (`[TeleClaude …]`, `[Orchestrator …]`) are NOT stripped — receivers identify them by the bracket and act accordingly.
- **User and assistant both matter**: plain human input after the anchor is mirrored, not only assistant output.
- **Hold trailing human turns**: a bundle whose final segment is `user` is trimmed before send — the held-back human turn stays past the cursor and ships with the next `agent_stop`'s reply. This enforces the invariant that human input always travels bundled with the agent's response, never alone.
- **Single bundled delivery**: all visible segments since the cursor are merged into ONE outer message per delivery, with inner markers preserving the temporal sequence. This collapses N user-prompt entries on the receiver into 1.
- **Debounced trigger**: agent_stops drive a per-source coalescing window (10s reset on each fresh signal) before delivery fires, so rapid multi-turn activity does not produce a burst of mid-turn deliveries.
- **Advance after handoff**: the cursor moves only after durable handoff succeeds:
  - local target: inbound message accepted by `process_message`
  - remote target: request accepted by Redis transport
- **Crash-safe handoff via in-flight pending bound**: before sending a bundle, the planned upper-bound timestamp is persisted to `pending_through_ts`. On successful delivery, an atomic upsert advances `delivered_through_ts` and clears `pending_through_ts`. On reconciliation, an orphaned `pending_through_ts > delivered_through_ts` triggers a **bounded replay**: the same range is collected from the transcript, framed into the same bundle, and re-sent under the same transport dedupe key. The receiver dedupes if it already accepted the bundle, or processes it for the first time if the prior send did not reach the queue. Cursor advance happens only after this replay handoff succeeds — pending is never blindly promoted.
- **Restart reconciliation**: startup runs the same replay logic against active links. The bounded-replay path runs first for any orphaned pending bound; only after its handoff is durable does the cursor advance to the bound, and the next iteration delivers segments past the bound as a fresh bundle.
- **Deterministic dedupe key**: transport dedupe keys for a bundle derive from link identity, source/target identity, the cursor at bundle start, and the planned upper-bound. The crash-safe pending bound prevents the upper-bound from drifting on replay, so the key remains stable across restart-after-handoff.
- **Listener records are untouched.** Link creation, reuse, and severance never insert, modify, or delete rows in `session_listeners`. The interaction between the two axes is purely runtime: while an active direct link exists for a `(caller, target)` pair, that caller's listener-driven notifications for that target are suppressed at delivery time. The listener row remains and resumes delivery on the next event after the link is severed. Any code path that calls `register_listener` or `unregister_listener` during link lifecycle is a bug.

## Primary flows

### 1. Direct conversation anchor

1. `create_or_reuse_direct_link` (fresh-create branch only) seeds `delivered_through_ts = now()` for both directional cursors so the per-link floor is authoritative regardless of either peer's session-level history.
2. A TeleClaude conversation bridge message is injected into the receiver session.
3. `deliver_inbound` stores `last_conversation_injected_at` on the receiver, gating future replays on that side.
4. Subsequent visible conversation activity in either session becomes eligible for mirroring; the floor is the per-link cursor on each direction.

### 2. Stop-time replay

1. `agent_stop` wakes the coordinator.
2. The coordinator schedules a debounced delivery for the source session — 10s
   coalescing window keyed on `source_session_id`. Every fresh agent_stop within
   the window cancels the pending timer and starts a new one.
3. When the window expires, conversation delivery loads all active links for
   the source session.
4. For each peer, it loads the directional cursor.
5. **Crash recovery first:** if `pending_through_ts > delivered_through_ts`, the
   bounded-replay path runs (see Startup reconciliation step 4). Only after the
   replay handoff is durable does processing continue with new segments past
   the pending bound.
6. It projects visible transcript segments since
   `max(last_conversation_injected_at, delivered_through_ts)`.
7. If the final projected segment has role `user`, it is trimmed off — that
   turn is unanswered and must wait for the next `agent_stop` to ride with
   the agent's reply. If trimming leaves no segments, delivery is skipped
   and the cursor stays put.
8. If any segments remain, it persists `pending_through_ts = latest_segment_ts`
   BEFORE sending, then formats all segments into ONE bundled message and
   submits a single `ProcessMessageCommand` to the peer.
9. On successful handoff, an atomic upsert advances
   `delivered_through_ts = latest_segment_ts` and clears `pending_through_ts`.

### 3. Startup reconciliation

1. Daemon startup restores adapters and inbound queue processing.
2. Lifecycle reconciliation scans live local sessions with a conversation anchor.
3. For each source session, it re-runs the same delivery logic used at stop time
   (bypassing the debounce window — recovery is immediate).
4. Per peer, if `pending_through_ts > delivered_through_ts`, the bounded-replay
   path runs first: rebuild the bundle from the transcript capped at the
   pending bound, re-send under the SAME dedupe key (receiver dedupes if it
   already accepted), then on success advance the cursor to the pending bound
   and clear pending.
5. After replay (or when no pending was set), any mirrored segments past the
   advanced cursor are delivered as a fresh bundle.

## Failure modes

- **Daemon restart after source output but before any send attempt**: no
  `pending_through_ts` was written for the next bundle. Startup reconciliation
  replays the missing visible segments from transcript truth as a fresh bundle.
- **Daemon restart after pre-write of `pending_through_ts` but before send,
  send-in-flight, or after send-success but before cursor advance**:
  `pending_through_ts` exists and exceeds `delivered_through_ts`. Reconciliation
  performs a **bounded replay**: it rebuilds the bundle from the transcript
  capped at the pending bound and re-sends under the SAME transport dedupe key.
  The receiver dedupes if it already accepted the bundle, or processes it for
  the first time if the prior send did not reach the queue. Cursor advances
  to the pending bound only after this replay returns durably.
- **Remote delivery failure**: when the send raises, the cursor stays at the
  previous `delivered_through_ts` and `pending_through_ts` is left in place.
  The next stop or startup reconciliation runs the bounded replay and tries
  again under the same dedupe key. For always-failing remotes the bundle stays
  pending until the link recovers — observable via the persisted pending value.
- **No anchor present**: no conversation replay is attempted for that session.
- **No transcript or unknown agent**: replay is skipped safely for that source session.
