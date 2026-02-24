# Implementation Plan: bidirectional-agent-links

## Approach

Implement a shared listener/link primitive with explicit modes:

- `worker_notify` mode: existing stop-notification behavior for orchestrator-worker flows
- `direct_link` mode: peer conversation link with member-based fan-out

Direct conversation becomes first-class listener behavior instead of a separate relay path.
This is a hard cutover: the legacy tmux polling relay is removed in this todo (no coexistence mode).

## Architecture

### Data model

- `conversation_links`
  - `link_id`
  - `mode` (`direct_link` or `gathering_link`)
  - `status` (`active`, `closed`)
  - `created_by_session_id`
  - timestamps
  - optional metadata JSON
- `conversation_link_members`
  - `link_id`
  - `session_id`
  - optional `participant_name`, `participant_number`, `role`
  - `joined_at`

### Runtime behavior

- Link lookup by member session ID
- Sender-excluded fan-out to other active members
- Distilled `agent_stop` output routing through direct link mode
- Single-party sever removes link and all members

## File Plan

| File                                      | Change                                                                          |
| ----------------------------------------- | ------------------------------------------------------------------------------- |
| `teleclaude/core/schema.sql`              | add link + member tables                                                        |
| `teleclaude/core/db_models.py`            | add ORM models                                                                  |
| `teleclaude/core/db.py`                   | add link CRUD/membership APIs                                                   |
| `teleclaude/core/session_listeners.py`    | add high-level link service helpers                                             |
| `teleclaude/mcp/tool_definitions.py`      | add `close_link` to `send_message`                                              |
| `teleclaude/mcp/handlers.py`              | `direct=true` handshake + `close_link` sever path; remove `_start_direct_relay` |
| `teleclaude/core/agent_coordinator.py`    | route linked `agent_stop` output to peers                                       |
| `teleclaude/transport/redis_transport.py` | support cross-computer linked output forwarding                                 |
| `teleclaude/core/session_cleanup.py`      | cleanup links on session end; remove relay-specific cleanup block               |
| `teleclaude/core/session_relay.py`        | remove legacy polling relay module                                              |
| `tests/unit/test_session_listeners.py`    | add link/membership tests                                                       |
| `tests/unit/test_bidirectional_links.py`  | add direct-link integration tests                                               |
| `tests/unit/test_session_relay.py`        | remove legacy relay tests; replace with link-focused coverage                   |

## Tasks

### Task 1: Link persistence + APIs

- [x] Implemented and verified

Add storage and APIs to:

- create/reuse link
- add/remove/list members
- lookup link by session
- sever link
- cleanup links by session

Acceptance:

- one link can hold 2+ members
- lookup by member returns peer list

### Task 2: Preserve worker listener behavior

- [x] Implemented and verified

Keep existing worker stop-notification flow untouched when direct links are not active.

Acceptance:

- existing `notify_stop` text flow still works for non-direct workflows

### Task 3: Legacy relay decommission (hard cutover)

- [x] Implemented and verified

Remove the tmux polling relay path and its callsites:

- delete `teleclaude/core/session_relay.py`
- remove `_start_direct_relay` and relay startup branch from `teleclaude__send_message`
- remove relay cleanup block from `teleclaude/core/session_cleanup.py`
- remove relay-only unit tests and replace with link coverage

Acceptance:

- no runtime code references `session_relay` or `_start_direct_relay`
- `direct=true` no longer starts any polling relay path
- non-direct notification flows still pass existing tests

### Task 4: Direct handshake in `send_message`

- [x] Implemented and verified

Update `teleclaude__send_message` behavior:

- `direct=true` creates or reuses a 2-member direct link
- avoids worker listener registration for that direct pair
- still delivers the initial message

Acceptance:

- first direct message creates link
- subsequent direct messages do not duplicate links

### Task 5: Single-party severing

- [x] Implemented and verified

Add `close_link=true` to `send_message`.

- if caller is a member, sever shared link in one action
- removal applies to both/all members immediately

Acceptance:

- either party can end the link without bilateral unsubscribe

### Task 6: Sender-excluded user-message routing

- [x] Implemented and verified

When a member-originated message is processed, route it to all other link members and never to sender.

Acceptance:

- 2-member link routes to one peer
- 3-member link routes to two peers

### Task 7: Distilled `agent_stop` output fan-out

- [x] Implemented and verified

In `agent_stop` handling:

- detect active direct link membership
- extract final output
- filter checkpoint/empty content
- inject framed output to peer members

Acceptance:

- peers receive framed final output only
- checkpoint responses do not cross

### Task 8: Cross-computer direct links

- [x] Implemented and verified

Extend forwarding contract to carry data needed for remote peer injection (not only stop metadata).

Acceptance:

- member on computer A receives linked output from member on computer B

### Task 9: Session-end cleanup

- [x] Implemented and verified

On session termination:

- remove session membership
- sever/cleanup affected links
- prevent orphan delivery attempts

Acceptance:

- no post-close injections to ended sessions

### Task 10: Gathering compatibility surface

- [x] Implemented and verified

Expose APIs required by `start-gathering-tool`:

- create multi-member link
- query ordered member metadata
- sender-excluded fan-out primitives

Acceptance:

- gathering todo can consume shared link primitive without legacy relay dependency

### Task 11: Tests

- [x] Implemented and verified

Unit coverage:

- link create/reuse/sever
- membership add/remove/query
- sender-excluded routing
- checkpoint filtering
- session cleanup behavior

Integration coverage:

- direct handshake link creation
- linked `agent_stop` output routing
- single-party `close_link` severing
- cross-computer routing
- regression guard: worker listener flow unchanged

## Risks

- Routing loop risk in peer mode
  - Mitigation: sender-excluded routing + explicit link mode checks
- Cross-computer payload mismatch
  - Mitigation: typed forwarding contract tests
- Cleanup leaks
  - Mitigation: mandatory cleanup hooks on session end + tests

## Sequence

1. Task 1-3 (foundations + relay decommission)
2. Task 4-5 (direct lifecycle)
3. Task 6-7 (routing semantics)
4. Task 8-9 (distributed + cleanup)
5. Task 10-11 (gathering alignment + verification)
