---
description: 'Restart-safe peer conversation replay built from transcript truth and directional delivery cursors.'
id: 'project/design/architecture/conversation-delivery'
scope: 'project'
type: 'design'
---

# Conversation Delivery — Design

## Purpose

Keep direct conversations correct across normal turns, human interjections, and daemon restarts.

This system is separate from one-shot session listeners. It owns peer conversation replay for persisted conversation links.

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
- **Visible content only**: replay includes visible `user` and `assistant` text blocks. TeleClaude-prefixed bridge messages are excluded by the conversation projector.
- **User and assistant both matter**: plain human input after the anchor is mirrored, not only assistant output.
- **Single bundled delivery**: all visible segments since the cursor are merged into ONE outer message per delivery, with inner markers preserving the temporal sequence. This collapses N user-prompt entries on the receiver into 1.
- **Debounced trigger**: agent_stops drive a per-source coalescing window (10s reset on each fresh signal) before delivery fires, so rapid multi-turn activity does not produce a burst of mid-turn deliveries.
- **Advance after handoff**: the cursor moves only after durable handoff succeeds:
  - local target: inbound message accepted by `process_message`
  - remote target: request accepted by Redis transport
- **Crash-safe handoff via in-flight pending bound**: before sending a bundle, the planned upper-bound timestamp is persisted to `pending_through_ts`. On successful delivery, an atomic upsert advances `delivered_through_ts` and clears `pending_through_ts`. Startup reconciliation promotes any orphaned `pending_through_ts > delivered_through_ts` to delivered (treats as already handed off) so the bundle is never re-sent under a different transport dedupe key when the source transcript has grown.
- **Restart reconciliation**: startup runs the same replay logic against active links. After promoting any orphaned pending bound, unseen mirrored segments after that bound are recovered as a fresh bundle.
- **Deterministic dedupe key**: transport dedupe keys for a bundle derive from link identity, source/target identity, the cursor at bundle start, and the planned upper-bound. The crash-safe pending bound prevents the upper-bound from drifting on replay, so the key remains stable across restart-after-handoff.

## Primary flows

### 1. Direct conversation anchor

1. A TeleClaude conversation bridge message is injected into a session.
2. `deliver_inbound` stores `last_conversation_injected_at` on the target session.
3. Subsequent visible conversation activity in that session becomes eligible for mirroring.

### 2. Stop-time replay

1. `agent_stop` wakes the coordinator.
2. The coordinator schedules a debounced delivery for the source session — 10s
   coalescing window keyed on `source_session_id`. Every fresh agent_stop within
   the window cancels the pending timer and starts a new one.
3. When the window expires, conversation delivery loads all active links for
   the source session.
4. For each peer, it loads the directional cursor (and promotes any orphaned
   `pending_through_ts` to `delivered_through_ts` first — see crash recovery).
5. It projects visible transcript segments since
   `max(last_conversation_injected_at, delivered_through_ts)`.
6. If any segments exist, it persists `pending_through_ts = latest_segment_ts`
   BEFORE sending, then formats all segments into ONE bundled message and
   submits a single `ProcessMessageCommand` to the peer.
7. On successful handoff, an atomic upsert advances
   `delivered_through_ts = latest_segment_ts` and clears `pending_through_ts`.

### 3. Startup reconciliation

1. Daemon startup restores adapters and inbound queue processing.
2. Lifecycle reconciliation scans live local sessions with a conversation anchor.
3. For each source session, it re-runs the same delivery logic used at stop time
   (bypassing the debounce window — recovery is immediate).
4. Per peer, if `pending_through_ts > delivered_through_ts`, the orphaned
   pending bound is promoted to delivered (the bundle was sent but the cursor
   write didn't complete before the crash) and `pending_through_ts` is cleared.
5. Any mirrored segments that arrived after the promoted cursor are replayed
   as a fresh bundle.

## Failure modes

- **Daemon restart after source output but before peer delivery**: no
  `pending_through_ts` was written. Startup reconciliation replays the missing
  visible segments from transcript truth as a fresh bundle.
- **Daemon restart after peer delivery but before cursor advance**:
  `pending_through_ts` exists and exceeds `delivered_through_ts`. Reconciliation
  promotes pending to delivered and skips the redelivery — the receiver already
  has the bundle, and its transport dedupe key would not have suppressed a
  second bundle whose range expanded with newly arrived transcript content.
- **Remote delivery failure**: `pending_through_ts` was written before the send
  attempt; if the send raises, the cursor stays at the previous `delivered_through_ts`
  and the in-flight pending value is left in place. The next stop or startup
  reconciliation will then promote it (assumes the receiver got it). For
  always-failing remotes this is a known limitation — a future health check
  should clear stale pending bounds.
- **No anchor present**: no conversation replay is attempted for that session.
- **No transcript or unknown agent**: replay is skipped safely for that source session.
