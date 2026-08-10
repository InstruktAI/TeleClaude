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

- A single agent-facing mirrored bundle per delivery whose body renders one
  canonical peer provenance header per source segment in temporal order. A
  human-authored segment renders `[TeleClaude - Peer
(<source-session-uuid>) · human:<human-name> · <utc-minute>]`; an
  agent-authored segment renders `[TeleClaude - Peer
(<source-session-uuid>) · agent:<runtime>/<thinking-mode> · <utc-minute>]`.
  The header is derived from typed segment authorship, never from transcript
  channel role. The bundle has no additional outer identity wrapper and no
  inner generic `--- Human @ ... ---` or `--- Agent @ ... ---` marker.
- A Discord admin projection of that bundle emits one ordered webhook message
  per eligible segment. Each Discord message contains only its segment body and
  uses the source author's per-message alias/avatar; the provenance header is
  retained in transcript truth but omitted from Discord copy.

- Advanced directional delivery cursors after successful durable handoff.

## Invariants

- **Transcript truth**: replay is computed from transcript content, not from hook payload bodies.
- **Session-local anchor**: `last_conversation_injected_at` marks the most recent TeleClaude conversation injection into a session.
- **Directional progress**: delivery is tracked per `(link_id, source_session_id, target_session_id)`.
- **Boundary is later(anchor, cursor)**: replay starts at the later of the session anchor and the persisted directional cursor.
- **Per-link cursor seeded at link creation**: when a fresh direct link is created, both directional cursors (`caller→target` and `target→caller`) are seeded with `now()` as `delivered_through_ts`. Without this floor, the sender side has no anchor refresh from the Direct Conversation intro (only the receiver does), so a stale `last_conversation_injected_at` from a prior link or fan-out would pull pre-link transcript content into the first bundle. The cursor floor is per-link and authoritative regardless of session-level anchor history. Reused links keep their existing cursors.

- **Visible content only**: replay includes visible `user` and `assistant` text blocks. Agent-CLI runtime artifacts (`<system-reminder>`, `<task-notification>`, hook-feedback prefixes) are stripped by the projector. TeleClaude notification and input-request envelopes are excluded from peer replay regardless of recipient visibility preferences. Other bracket-marked machine messages remain governed by their existing projection category.

- **User and assistant both matter**: plain human input after the anchor is mirrored, not only assistant output.

- **Authorship, not channel, sets the segment header.** A human identity is carried only by a segment the projector classified as human-authored. Every eligible machine-originated segment — orchestrator, worker, system, peer bridge, or assistant output — carries its resolved machine identity. Authorship travels with the segment from projection and is never re-derived from transcript channel role.
- **Segments are cut on authorship as well as channel.** Consecutive blocks merge only when they share channel role and resolved author identity, so adjacent machine and human turns on the user channel never collapse under one header.

- **Authorship metadata is complete before rendering.** Every projected segment
  carries the source TeleClaude session UUID, original timestamp, explicit
  author class, and either the human display identity, machine role, or agent
  runtime plus thinking mode. Rendering never reconstructs identity from a
  generic channel role or guesses author class from display text.
- **One author header replaces stacked framing.** Each projected segment renders
  exactly one peer header. The full source session UUID remains visible, the
  displayed timestamp is UTC at minute precision, and exact timestamp precision
  remains in transcript and delivery metadata.

- **Peer replay is filtered by original source, per destination.** A peer header
  identifies conversational content; it is not a blanket exclusion marker. For
  each target, only embedded peer segments whose original source session equals
  that target are suppressed. Segments from every other source remain eligible,
  regardless of whether the same human participates in more than one linked
  session.
- **Compound peer bundles retain eligible segments independently.** A bridge
  block may contain several canonical peer segments. Each segment is evaluated
  against the target separately, and retained segments keep their original
  order, header, body, author identity, and source-session attribution.
- **Only local human turns require reply pairing.** The trailing unanswered-turn
  hold applies to locally-authored human user-channel segments. A retained peer
  segment is already conversational content from another session and is never
  withheld merely because its containing transcript block uses the user channel
  or it is the last visible segment.
- **Visible occurrence and replay progress are separate clocks.** A retained
  peer segment preserves the original visible occurrence minute already
  rendered in its header. Full-precision provenance remains in the originating
  transcript and delivery metadata; onward relay introduces no cross-hop
  provenance store. Pending bounds, directional cursors, bounded replay, and
  deterministic dedupe continue to use the timestamp of the containing entry in
  the current source session's transcript. An embedded header time is never a
  cursor bound.
- **Malformed peer framing fails stuck.** A visible block beginning with the peer
  prefix must parse completely as canonical peer segments before any of it is
  eligible. Ambiguous or malformed framing aborts that peer delivery, records an
  explicit failure, and leaves pending and delivered cursor state unchanged; it
  is never silently dropped or relabelled as a local author.

- **Hold trailing human turns**: the trailing run of `user`-channel segments is trimmed before send — the held-back turns stay past the cursor and ship with the next `agent_stop`'s reply. This enforces the invariant that human input always travels bundled with the agent's response, never alone. The run may be longer than one segment because authorship also cuts segments.

- **Single agent-facing transport delivery, segment-level presentation.** All
  visible segments since the cursor are handed off to the peer agent as one
  transport message, with one complete provenance header per segment preserving
  temporal sequence. That crash-safe handoff remains the cursor/dedupe unit.
  Discord presentation is a separate projection: it parses the same segment
  boundaries and emits one ordered webhook message per segment, so the agent's
  input is not multiplied and human-visible authorship is not collapsed.
- **Discord identity is source-owned.** Agent segments resolve only to Codex,
  Claude, or Gemini presentation metadata carried by the source author token;
  human and machine-role segments retain their source display identity. The
  intermediary session, target agent, and TeleClaude webhook default never
  replace a resolved author. A missing optional human avatar does not change the
  alias.

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
6. It projects visible transcript blocks since
   `max(last_conversation_injected_at, delivered_through_ts)`, retaining the
   current source transcript entry timestamp as the replay-progress timestamp.
7. For the current target, each canonical peer block is parsed completely and
   filtered per embedded segment. Segments originally sourced from the target
   are suppressed; segments from other sessions retain their original rendered
   header and body. A malformed peer block aborts this delivery slice without
   advancing or pre-writing cursor state.
8. The trailing run of locally-authored human user-channel segments is trimmed
   off — those turns are unanswered and must wait for the next `agent_stop` to
   ride with the agent's reply. Retained peer segments do not qualify for this
   hold, even though their containing transcript block uses the user channel.
   If trimming leaves no segments, delivery is skipped and the cursor stays put.
9. If any segments remain, it persists
   `pending_through_ts = latest_source_entry_ts` BEFORE sending, then formats
   local segments and preserves retained peer segments into ONE bundled message
   and submits a single `ProcessMessageCommand` to the peer.
10. On successful handoff, an atomic upsert advances
    `delivered_through_ts = latest_source_entry_ts` and clears
    `pending_through_ts`.
11. When the accepted peer bundle later reaches Discord admin reflection,
    projection parses its canonical segments and sends each body separately in
    source order with that segment's webhook alias/avatar. The projection
    watermark advances for the transcript entry only after the ordered
    reflection pass; it never creates additional agent inputs or delivery-state
    rows.

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

- **Malformed peer-prefixed transcript block:** strict parsing fails before
  handoff or pending-bound pre-write. The delivery remains at the same source
  boundary and logs the target, link, and source session for intervention; no
  substring is silently discarded and no generic local author is substituted.
- **Discord projection cannot recover canonical framing or required identity:**
  no peer segment is sent and the user-reflection watermark remains at that
  entry. The projector emits a structured, body-free error carrying the session,
  entry timestamp, and failure class, but it does not block projection of the
  agent output that follows the entry. A later projection signal retries after
  the framing is repaired or the missing closed identity becomes supported.
  Cursor/dedupe state for direct-link transport remains unchanged.
- **Discord webhook transport fails after valid decomposition:** reflection
  remains best-effort. Each failed segment emits a structured, body-free error
  with its ordinal and author class; later segments are still attempted, the
  user-reflection watermark advances after the pass, and no retry or bot-authored
  fallback is synthesized. Without per-platform idempotency receipts, retrying
  the whole entry would duplicate segments that Discord already accepted.
