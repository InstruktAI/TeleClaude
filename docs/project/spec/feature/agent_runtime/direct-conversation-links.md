---
id: 'project/spec/feature/agent_runtime/direct-conversation-links'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Bidirectional message routing between two (or more) agent sessions via the `--direct` ignition flow. A conversation link is established once, peer turn-complete outputs are then cross-shared automatically, and `--close-link` severs the link for every member.'
---

# Direct Conversation Links — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

A **conversation link** is the agent_runtime aggregate that turns two (or more) sessions into peers whose subsequent turn-complete outputs are delivered to one another automatically, without re-issuing `telec sessions send` per turn.

The link is established by a single act of *ignition*: any party — typically the caller of `telec sessions send <peer> "<msg>" --direct` — creates the link, the receiving session is added as the second member, and from that moment forward the active-conversation channel supersedes passive listener notifications between the pair. Either party may sever the link with `--close-link`, which closes it for all members at once.

The link is an associative aggregate (`ConversationLink` + `ConversationLinkMember`) backed by SQLite; it survives daemon restarts and is the canonical record of "these sessions are currently talking to each other."

## Canonical fields

### Behavioral contract

#### Ignition: link creation via `--direct`

```
Given session A (caller) and session B (target) both exist and are open
And no direct link is currently active between A and B
When the caller invokes `telec sessions send B "<message>" --direct`
Then the API resolves caller identity from x-caller-session-id
And `_create_direct_link` calls `create_or_reuse_direct_link(caller=A, target=B, ...)`
And a new `conversation_link` row is written with mode="direct_link" and created_by_session_id=A
And two `conversation_link_member` rows are upserted: A as participant_number=1, B as participant_number=2, both role="peer"
And per-link delivery state cursors are anchored at now() so the first cross-share never includes pre-link transcript content
And `_format_direct_conversation_intro` wraps the initial message with the peer header + rules block (no follow-up sends, default emit=false, protocol markers)
And `_deliver_direct_message` delivers the intro message to peer B
And the response carries status="success", mode="direct", link_state="created", delivered_to=1, members=2
```

#### Ignition: link creation at session-start with `--direct`

```
Given the caller spawns a new session via the API with request.direct=true
When `create_session` completes and returns the new session_id
Then `_link_direct_sessions` runs, calling `create_or_reuse_direct_link` for (caller_session_id, new_session_id)
And the same two-member link aggregate is written
And the launch message is wrapped with the direct-conversation intro before delivery
And the listener axis is untouched — the two subscription axes (listeners and links) remain orthogonal
```

#### Reuse semantics

```
Given a direct link is already active between sessions A and B
When the caller calls `telec sessions send B "<msg>" --direct` again
Then `_create_direct_link` calls `resolve_link_for_sender_target` first
And finds the existing link
And returns `_active_direct_link_response(link_id, already_active=True)` with status="error"
And the message body explains: "A direct link is already active with this peer. We agreed not to use send during direct conversation as it obfuscates the exchange from the observer. Your turn-complete output is automatically shared — just talk."
And NO new link is created, NO duplicate members are written, and the original message is NOT delivered via this path
```

```
Given a stale duplicate link row exists for the same pair (e.g., a prior crash mid-creation)
When `create_or_reuse_direct_link` runs under the canonical per-pair asyncio lock
Then it selects the first active link as the survivor
And severs every duplicate via `db.sever_conversation_link`
And re-upserts both members on the survivor (idempotent participant_number=1 for caller, =2 for target)
And returns (link, reused=True)
```

#### Cross-sharing of turn-complete outputs

```
Given an active direct link exists between members A and B
And the per-link delivery cursors were anchored at link-creation time
When member A's agent completes a turn (turn-complete signal from the agent CLI hook stream)
Then the conversation_delivery pipeline scans A's transcript since A's outbound delivery cursor
And bundles the new turn-complete segments for delivery
And routes the bundle into peer B's tmux as the next input
And advances the (link, A→B) delivery cursor to the latest bundled timestamp
And the symmetric path applies for B → A
And neither party needs to re-invoke `telec sessions send` for follow-up turns
```

#### Listener suppression while linked

```
Given a one-shot or persistent listener is registered with caller=A, target=B
And an active direct link of mode="direct_link" exists between A and B
When B's stop event fires and `_notify_listeners` iterates
Then `db.get_active_link_between_sessions(A, B, mode="direct_link")` returns the active link
And the per-listener delivery is skipped (NOT removed — the listener row is preserved)
And listener delivery resumes on the next event after the link is severed
```

#### Closure: `--close-link` severs for ALL members

```
Given a direct link exists between A and B (and conceivably more members in a multi-member scenario)
When any member invokes `telec sessions send B --close-link` (optionally with a final message)
Then `_handle_close_link_request` requires caller session identity
And calls `resolve_link_for_sender_target(caller, target)` — returns "no active direct link found" if none
And, if a final message was supplied, processes it via the normal message pipeline before severing
And calls `close_link_for_member(caller, target)` which enumerates every active link between (caller, target) and severs each via `db.sever_conversation_link`
And severance closes the link for EVERY member of that link, not only the caller
And subsequent turn-complete outputs are no longer cross-shared
And suppressed listener rows resume firing on the next stop event
And the response carries status="success", mode="direct", action="closed", link_id=<closed link>
```

#### Race rejection on a non-direct send

```
Given an active direct link exists between caller A and target B
When A attempts `telec sessions send B "<msg>"` WITHOUT `--direct`
Then `_reject_existing_direct_link` resolves the existing link
And returns `_active_direct_link_response(link_id, already_active=False)` with status="error"
And NO message is delivered through the plain-send path
And the link remains intact
```

#### Member roster & multi-peer model

```
Given a `ConversationLink` aggregate with one or more `ConversationLinkMember` rows
When any consumer calls `get_link_members(link_id)`
Then it returns every member row in join order
And `get_peer_members(link_id, sender)` returns all members EXCEPT the sender — making fan-out trivially N-way
And `_deliver_direct_message` iterates the resolved peers; if all peer sessions are missing/closed, delivery falls back to the originally-addressed target_session_id
And v1 creates exclusively two-member direct links via `create_or_reuse_direct_link`; the aggregate shape itself is associative and not restricted to two
```

#### Lifecycle interaction: peer ended mid-conversation

```
Given a direct link exists between A and B
And session B ends (explicit close, idle timeout, or crash-driven termination)
When `terminate_session` runs and calls `cleanup_session_resources`
Then `cleanup_session_links(B)` is invoked
And `db.cleanup_conversation_links_for_session(B)` severs every active link involving B
And the link with A is closed for all members
And any subsequent direct send from A toward B is rejected via the normal "no active target sessions" / closed-session path
```

```
Given a delivery attempt fans out to multiple peers
When one peer session is missing or its lifecycle_status is in {closed, closing}
Then `_deliver_direct_message` logs and skips that peer
And continues delivering to the remaining live peers
And returns delivered_to=<count of live peers actually delivered>
And if delivered_to==0, the response carries status="error" with message "No active target sessions available for delivery"
```

#### Concurrency safety

```
Given two callers concurrently attempt to ignite a direct link for the same (A,B) pair
When both reach `create_or_reuse_direct_link`
Then a canonical per-pair `asyncio.Lock` (keyed by sorted (session_a, session_b)) serializes them
And whichever runs first creates the link
And the second observes the existing active link and reuses it, severing any duplicate
And no concurrent path produces orphaned link rows or split member rosters
```

### Implementation pointers (v1)

- Link aggregate: `teleclaude/core/session_listeners.py`
  - Dataclasses: `ConversationLink` (`L42`), `ConversationLinkMember` (`L56`)
  - Row converters: `_to_conversation_link` (`L79`), `_to_conversation_link_member` (`L105`)
  - Per-pair canonical lock: `_get_pair_lock` (`L68`)
  - CRUD: `create_link` (`L444`), `add_link_member` (`L460`), `get_link_members` (`L480`), `get_link` (`L486`), `get_active_links_for_session` (`L494`)
  - Ignition + reuse: `create_or_reuse_direct_link` (`L504`) — anchors per-link delivery cursors at creation time
  - Resolution: `resolve_link_for_sender_target` (`L585`), `get_peer_members` (`L599`)
  - Closure: `close_link` (`L609`), `close_link_for_member` (`L614`), `cleanup_session_links` (`L636`)
  - Listener suppression while linked: `_notify_listeners` (`L330`) checks `db.get_active_link_between_sessions(..., mode="direct_link")` and preserves the listener row
- API surface: `teleclaude/api/sessions_routes.py`
  - Intro formatter: `_format_direct_conversation_intro` (`L129`)
  - New-session ignition: `_link_direct_sessions` (`L340`)
  - Active-link error response: `_active_direct_link_response` (`L633`)
  - Close path: `_handle_close_link_request` (`L735`)
  - Build context: `_build_direct_message_context` (`L777`)
  - Link create-or-reuse routing: `_create_direct_link` (`L797`)
  - Direct delivery: `_deliver_direct_message` (`L827`)
  - Direct send handler: `_handle_direct_message_request` (`L852`)
  - Plain-send race rejection: `_reject_existing_direct_link` (`L905`)
  - Wired into `send_message_endpoint` (`L922`) and `create_session` (`L529`)
- Session-end teardown: `teleclaude/core/session_cleanup.py` — `cleanup_session_resources` (`L146`) invokes `cleanup_session_links(session_id)` (`L163`)
- CLI surface: `telec sessions send <id> "<msg>" --direct` (ignites) and `telec sessions send <id> --close-link` (severs for all members)

### Cross-context references

- **identity**: caller is bound via `CallerIdentity.session_id` (from `x-caller-session-id` / token); ignition requires a non-web caller session id (`_extract_initiator_session_id` rejects web origins for `--direct`). The link aggregate stores session ids only; the principal binding is owned upstream by identity.
- **session_subscriptions** (peer feature): the listener axis (one-shot or persistent stop notifications) and the link axis are intentionally orthogonal. While a link is active, listener delivery for the same (caller, target) pair is suppressed at `_notify_listeners`; the listener row is preserved and resumes after closure.
- **conversation_delivery** (peer feature inside agent_runtime): the cross-sharing of turn-complete outputs (per-link cursor advancement, transcript-since-cursor bundling, reconciliation of orphaned `pending_through_ts`) lives in `teleclaude/core/conversation_delivery.py` and is invoked at hook-stop and at startup via `reconcile_outstanding_conversation_deliveries` — see daemon-lifecycle spec.
- **integration**: no direct dependency. Sessions whose initiator/target is an external (non-tmux) adapter are not eligible for ignition; `_link_direct_sessions` is only wired from session-spawn paths whose caller is an agent session.

## Known caveats

- **Ignition requires a caller session identity.** Pure web / unidentified callers cannot ignite a link (`_extract_initiator_session_id` raises 400 for `request.direct` without identity.session_id). The link is always between two agent sessions, not a human and a session.
- **Closure is associative, not caller-scoped.** Any member calling `--close-link` severs the link for ALL members. There is no "leave but keep the link alive for the others" path in v1.
- **Reuse short-circuits with an error, not a success.** Calling `--direct` a second time on an already-linked pair returns status="error" with a rules reminder; the message text is NOT delivered through this path. Members are expected to "just talk" — turn-complete outputs are cross-shared automatically.
- **Plain-send during an active link is rejected.** A non-direct `telec sessions send` toward a peer with whom a direct link is active is refused via `_reject_existing_direct_link` to prevent obfuscating the exchange from observers.
- **Multi-member is structurally supported, not exposed.** `ConversationLink` + `ConversationLinkMember` can represent N≥2 members, and `get_peer_members` / `_deliver_direct_message` already fan out N-way; v1 only exposes a two-member direct ignition through `create_or_reuse_direct_link`. Gathering-mode links (mode="gathering_link") use the same aggregate.
- **Per-link delivery cursors are anchored at creation, not at first turn.** Pre-link transcript content never appears in the first cross-share. This is the explicit reason the cursors are upserted inside `create_or_reuse_direct_link` rather than lazily at first delivery.
- **Stale duplicate rows are silently healed on next ignition.** If the database contains more than one active link for the same pair (e.g., a prior crash mid-creation), `create_or_reuse_direct_link` keeps the first and severs the rest under the canonical pair lock. No external reconciliation pass is needed.
- **Listener rows survive suppression.** Suppression while linked does not remove the listener; once the link severs, the next stop event fires the listener normally. This avoids re-subscription ceremony on every close.
