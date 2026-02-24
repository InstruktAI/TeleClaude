# Requirements: bidirectional-agent-links

## Goal

Deliver a shared listener/link primitive that supports:

- 2-party direct peer conversation (`direct=true`)
- 3+ participant conversations as the base primitive for gathering orchestration
- strict coexistence with existing worker notification listeners

## Key Design Contract

- Worker notification listeners and direct conversation links are distinct listener modes.
- A direct conversation uses one shared link object with member sessions.
- Any member can sever the link in one action.

## Success Criteria

### SC-1: One Link Object, Two Members (Direct Mode)

When A starts direct conversation with B, system creates/reuses one shared link containing both session IDs.

Verification:

- Query link store after handshake.
- Confirm one active link object with two members (A, B).
- Confirm no duplicate one-way rows are required.

### SC-2: Link Supports 3+ Members (Gathering-Ready Primitive)

Link model supports N members with optional participant metadata (name, number, role).

Verification:

- Create link with 3 participants.
- Confirm membership persists and can be queried by session ID.
- Confirm 2-party links work without requiring numbering.

### SC-3: Direct Handshake Behavior

`send_message(..., direct=true)` must:

- deliver initial message
- create/reuse direct link
- suppress worker-style stop-notification listener registration for that pair

Verification:

- Handshake from A to B returns link-created/reused result.
- A does not receive worker stop notification text for B while link active.

### SC-4: Sender-Excluded Fan-Out for User Messages

When a message is sent by a link member, link fan-out targets all other active members and excludes sender.

Verification:

- In a 2-member link, sender message is delivered only to the peer.
- In a 3-member link, sender message is delivered to the other two only.

### SC-5: Distilled `agent_stop` Output Fan-Out

For linked sessions, only distilled final `agent_stop` output crosses to peers as framed input.

Verification:

- Trigger `agent_stop` on A.
- Confirm B receives framed output from A.
- Confirm tool-call payloads/intermediate reasoning are not forwarded.

### SC-6: Checkpoint and Empty Output Filtering

Checkpoint responses and empty output never cross a link and do not consume turn budget.

Verification:

- Trigger checkpoint response turn.
- Confirm no peer injection for that turn.

### SC-7: Single-Party Link Severing

Any member can terminate the shared link (e.g., `close_link=true`), and link is removed for all members.

Verification:

- A closes link; B no longer receives A output and vice versa.
- No second unsubscribe action is required.

### SC-8: Session-End Cleanup

If any member session ends, links involving that session are cleaned and no orphan injection occurs.

Verification:

- End one member session.
- Confirm link removed and no injection attempts to closed tmux session.

### SC-9: Coexistence with Existing Worker Mode

Non-direct workflows retain existing stop-notification behavior and `get_session_data`-first inspection model.

Verification:

- Standard worker dispatch without direct mode still emits existing stop notification text.
- `get_session_data` remains unchanged.

### SC-10: Cross-Computer Link Routing

Direct link fan-out works across computers using existing Redis transport, including forwarded stop payloads required for peer injection.

Verification:

- Create cross-computer direct link.
- Trigger stop on remote member and confirm local peer receives framed output.

## Constraints

1. No breaking changes to worker notification flow.
2. Works for Claude, Gemini, and Codex sessions.
3. Compatible with upcoming `start-gathering-tool` orchestration.
4. Link lifecycle can be in-memory or durable, but cleanup guarantees must hold.

## Out of Scope

- Gathering talking-piece enforcement and phase orchestration.
- Group policy logic beyond sender-excluded fan-out and membership management.
- Persistent links across daemon restart if not selected in implementation.
