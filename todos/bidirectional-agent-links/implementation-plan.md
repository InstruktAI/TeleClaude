# Implementation Plan: bidirectional-agent-links

## Approach

Implement a shared listener/link primitive with explicit modes:

- `worker_notify` mode: existing stop-notification behavior for orchestrator-worker flows
- `direct_link` mode: peer conversation link with member-based fan-out

Direct conversation becomes first-class listener behavior instead of a separate relay path.

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

| File                                      | Change                                            |
| ----------------------------------------- | ------------------------------------------------- |
| `teleclaude/core/schema.sql`              | add link + member tables                          |
| `teleclaude/core/db_models.py`            | add ORM models                                    |
| `teleclaude/core/db.py`                   | add link CRUD/membership APIs                     |
| `teleclaude/core/session_listeners.py`    | add high-level link service helpers               |
| `teleclaude/mcp/tool_definitions.py`      | add `close_link` to `send_message`                |
| `teleclaude/mcp/handlers.py`              | `direct=true` handshake + `close_link` sever path |
| `teleclaude/core/agent_coordinator.py`    | route linked `agent_stop` output to peers         |
| `teleclaude/transport/redis_transport.py` | support cross-computer linked output forwarding   |
| `teleclaude/core/session_cleanup.py`      | cleanup links on session end                      |
| `tests/unit/test_session_listeners.py`    | add link/membership tests                         |
| `tests/unit/test_bidirectional_links.py`  | add direct-link integration tests                 |

## Tasks

### Task 1: Link persistence + APIs

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

Keep existing worker stop-notification flow untouched when direct links are not active.

Acceptance:

- existing `notify_stop` text flow still works for non-direct workflows

### Task 3: Direct handshake in `send_message`

Update `teleclaude__send_message` behavior:

- `direct=true` creates or reuses a 2-member direct link
- avoids worker listener registration for that direct pair
- still delivers the initial message

Acceptance:

- first direct message creates link
- subsequent direct messages do not duplicate links

### Task 4: Single-party severing

Add `close_link=true` to `send_message`.

- if caller is a member, sever shared link in one action
- removal applies to both/all members immediately

Acceptance:

- either party can end the link without bilateral unsubscribe

### Task 5: Sender-excluded user-message routing

When a member-originated message is processed, route it to all other link members and never to sender.

Acceptance:

- 2-member link routes to one peer
- 3-member link routes to two peers

### Task 6: Distilled `agent_stop` output fan-out

In `agent_stop` handling:

- detect active direct link membership
- extract final output
- filter checkpoint/empty content
- inject framed output to peer members

Acceptance:

- peers receive framed final output only
- checkpoint responses do not cross

### Task 7: Cross-computer direct links

Extend forwarding contract to carry data needed for remote peer injection (not only stop metadata).

Acceptance:

- member on computer A receives linked output from member on computer B

### Task 8: Session-end cleanup

On session termination:

- remove session membership
- sever/cleanup affected links
- prevent orphan delivery attempts

Acceptance:

- no post-close injections to ended sessions

### Task 9: Gathering compatibility surface

Expose APIs required by `start-gathering-tool`:

- create multi-member link
- query ordered member metadata
- sender-excluded fan-out primitives

Acceptance:

- gathering todo can consume shared link primitive without legacy relay dependency

### Task 10: Tests

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

1. Task 1-2 (foundations)
2. Task 3-4 (direct lifecycle)
3. Task 5-6 (routing semantics)
4. Task 7-8 (distributed + cleanup)
5. Task 9-10 (gathering alignment + verification)
