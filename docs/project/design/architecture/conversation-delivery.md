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

- Mirrored assistant messages framed as `[TeleClaude Linked output from ...]`
- Mirrored plain user messages framed as `[TeleClaude Human in the Loop from ...]`
- Advanced directional delivery cursors after successful durable handoff

## Invariants

- **Transcript truth**: replay is computed from transcript content, not from hook payload bodies.
- **Session-local anchor**: `last_conversation_injected_at` marks the most recent TeleClaude conversation injection into a session.
- **Directional progress**: delivery is tracked per `(link_id, source_session_id, target_session_id)`.
- **Boundary is later(anchor, cursor)**: replay starts at the later of the session anchor and the persisted directional cursor.
- **Visible content only**: replay includes visible `user` and `assistant` text blocks. TeleClaude-prefixed bridge messages are excluded by the conversation projector.
- **User and assistant both matter**: plain human input after the anchor is mirrored, not only assistant output.
- **Advance after handoff**: the cursor moves only after durable handoff succeeds:
  - local target: inbound message accepted by `process_message`
  - remote target: request accepted by Redis transport
- **Restart reconciliation**: startup runs the same replay logic against active links, so unseen mirrored segments are recovered after daemon restart.
- **Deterministic dedupe key**: transport dedupe keys are derived from link identity, source/target identity, role, and timestamp slice. No separate delivery UUID is introduced.

## Primary flows

### 1. Direct conversation anchor

1. A TeleClaude conversation bridge message is injected into a session.
2. `deliver_inbound` stores `last_conversation_injected_at` on the target session.
3. Subsequent visible conversation activity in that session becomes eligible for mirroring.

### 2. Stop-time replay

1. `agent_stop` wakes the coordinator.
2. Conversation delivery loads all active links for the source session.
3. For each peer, it loads the directional cursor.
4. It projects visible transcript segments since `max(last_conversation_injected_at, delivered_through_ts)`.
5. It frames assistant segments as linked output and user segments as human-in-the-loop.
6. After each successful peer delivery, it advances `delivered_through_ts`.

### 3. Startup reconciliation

1. Daemon startup restores adapters and inbound queue processing.
2. Lifecycle reconciliation scans live local sessions with a conversation anchor.
3. For each source session, it re-runs the same delivery logic used at stop time.
4. Any mirrored segments that were not fully delivered before restart are replayed.

## Failure modes

- **Daemon restart after source output but before peer delivery**: startup reconciliation replays the missing visible segments from transcript truth.
- **Daemon restart after peer delivery but before cursor advance**: deterministic transport dedupe suppresses duplicate enqueue.
- **Remote delivery failure**: the cursor stays behind; a later stop or startup reconciliation retries the same slice.
- **No anchor present**: no conversation replay is attempted for that session.
- **No transcript or unknown agent**: replay is skipped safely for that source session.
