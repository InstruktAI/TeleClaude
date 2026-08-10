---
description: 'Bidirectional message routing between two (or more) agent sessions via the `--direct` ignition flow. A conversation link is established once, peer turn-complete outputs are then cross-shared automatically, and `--close-link` severs the link for every member.'
visibility: 'public'
---

# Direct Conversation Links — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

A **conversation link** is the agent_runtime aggregate that turns two (or more) sessions into peers whose subsequent turn-complete outputs are delivered to one another automatically, without re-issuing `telec sessions send` per turn.

The link is established by a single act of _ignition_: any party — typically the caller of `telec sessions send <peer> "<msg>" --direct` — creates the link, the receiving session is added as the second member, and from that moment forward the active-conversation channel supersedes passive listener notifications between the pair. Either party may sever the link with `--close-link`, which closes it for all members at once.

The link is an associative aggregate of a link record and its member records, persisted durably by agent_runtime; it survives service restarts and is the canonical record of "these sessions are currently talking to each other."

## Canonical fields

### Use cases

#### Ignition: link creation via `--direct`

```
Given session A (caller) and session B (target) both exist and are open
And no direct link is currently active between A and B
When the caller invokes `telec sessions send B "<message>" --direct`
Then the agent_runtime service resolves caller identity
And dispatches a direct-link creation request for (caller=A, target=B)
And a new direct-mode link is recorded with creator=A
And two member entries are upserted: A as participant 1, B as participant 2, both with role "peer"
And per-link delivery cursors are anchored at link-creation time so the first cross-share never includes pre-link transcript content
And the initial message is wrapped with a peer header and a rules block before delivery
And the wrapped message is delivered to peer B
And the response reports a successful create, with the count of members and the count of peers the message reached
```

#### Ignition: link creation at session-start with `--direct`

```
Given the caller spawns a new session via the create-session flow with the direct flag set
When session creation completes and returns the new session id
Then the agent_runtime service ignites a direct link for (caller_session_id, new_session_id)
And the same two-member link aggregate is written
And the launch message is wrapped with the direct-conversation intro before delivery
And the listener axis is untouched — the two subscription axes (listeners and links) remain orthogonal
```

#### Reuse semantics

```
Given a direct link is already active between sessions A and B
When the caller calls `telec sessions send B "<msg>" --direct` again
Then the ignition path first resolves any existing active link for the (A, B) pair
And finds the existing link
And returns an error response indicating the link is already active, identifying the link
And the message body explains: "A direct link is already active with this peer. We agreed not to use send during direct conversation as it obfuscates the exchange from the observer. Your turn-complete output is automatically shared — just talk."
And NO new link is created, NO duplicate members are written, and the original message is NOT delivered via this path
```

```
Given a stale duplicate link row exists for the same pair (e.g., a prior crash mid-creation)
When the ignition path runs under the canonical per-pair lock
Then it selects the first active link as the survivor
And severs every duplicate
And re-upserts both members on the survivor (idempotent: caller stays participant 1, target stays participant 2)
And returns the survivor link as reused
```

#### Cross-sharing of turn-complete outputs

```
Given an active direct link exists between members A and B
And the per-link delivery cursors were anchored at link-creation time
When member A's agent completes a turn (turn-complete signal from the agent CLI hook stream)
Then the conversation-delivery pipeline scans A's transcript since A's outbound delivery cursor
And bundles the new turn-complete segments for delivery
And routes the bundle into peer B's host pane as the next input
And advances the (link, A→B) delivery cursor to the latest bundled timestamp
And the symmetric path applies for B → A
And neither party needs to re-invoke `telec sessions send` for follow-up turns
```

#### UC-DCL1: Non-bridge inter-actor turns cross-deliver; peer-bridge blocks never loop

```
Given an active direct link exists between members A and B
And B's transcript contains a `[TeleClaude - Peer (A) ...]` block that was cross-delivered earlier
And B's transcript contains an `[Orchestrator ...]` block typed into B
When the cross-delivery collector bundles B's turn for A
Then the peer-bridge block is excluded from the bundle
And the orchestrator block is delivered as a real segment
And no A-to-B-to-A echo segment is produced
```

#### Listener suppression while linked

```
Given a one-shot or persistent listener is registered with caller=A, target=B
And an active direct link of mode "direct_link" exists between A and B
When B's stop event fires and listener notification iterates
Then the active-link check between A and B returns the active link
And the per-listener delivery is skipped (NOT removed — the listener row is preserved)
And listener delivery resumes on the next event after the link is severed
```

#### Closure: `--close-link` severs for ALL members

```
Given a direct link exists between A and B (and conceivably more members in a multi-member scenario)
When any member invokes `telec sessions send B --close-link` (optionally with a final message)
Then the close path requires caller session identity
And resolves any active direct link for the (caller, target) pair — responding "no active direct link found" if none
And, if a final message was supplied, processes it via the normal message pipeline before severing
And invokes the closure path for the caller against the target, enumerating every active link between (caller, target) and severing each
And severance closes the link for EVERY member of that link, not only the caller
And subsequent turn-complete outputs are no longer cross-shared
And suppressed listener rows resume firing on the next stop event
And the response reports a successful close, identifying the closed link
```

#### Race rejection on a non-direct send

```
Given an active direct link exists between caller A and target B
When A attempts `telec sessions send B "<msg>"` WITHOUT `--direct`
Then the plain-send path rejects with an error identifying the active link
And NO message is delivered through the plain-send path
And the link remains intact
```

#### Member roster & multi-peer model

```
Given a conversation-link aggregate with one or more member entries
When any consumer asks for the link's members
Then it returns every member entry in join order
And asking for peer members against a given sender returns all members EXCEPT the sender — making fan-out trivially N-way
And the direct-delivery path iterates the resolved peers; if all peer sessions are missing/closed, delivery falls back to the originally-addressed target session
And v1 creates exclusively two-member direct links via the standard ignition path; the aggregate shape itself is associative and not restricted to two
```

#### Lifecycle interaction: peer ended mid-conversation

```
Given a direct link exists between A and B
And session B ends (explicit close, idle timeout, or crash-driven termination)
When session termination runs and the resource-cleanup path executes
Then the link-cleanup step is invoked for B
And every active link involving B is severed
And the link with A is closed for all members
And any subsequent direct send from A toward B is rejected via the normal "no active target sessions" / closed-session path
```

```
Given a delivery attempt fans out to multiple peers
When one peer session is missing or its lifecycle status is closed or closing
Then the direct-delivery path logs and skips that peer
And continues delivering to the remaining live peers
And reports the count of live peers actually delivered
And if no peers were reached, the response is an error: "No active target sessions available for delivery"
```

#### Concurrency safety

```
Given two callers concurrently attempt to ignite a direct link for the same (A,B) pair
When both reach the ignition path
Then a canonical per-pair lock keyed by sorted (session_a, session_b) serializes them
And whichever runs first creates the link
And the second observes the existing active link and reuses it, severing any duplicate
And no concurrent path produces orphaned link rows or split member rosters
```

#### UC-DCL2: Cross-delivered segment headers state actual authorship

```
Given an active direct link exists between sessions A and B
And one outbound bundle from B contains an orchestrator-authored segment, a human-authored segment, and an agent-authored segment
When the conversation-delivery pipeline renders the bundle for A
Then every segment remains separate according to its actual authorship
And the human segment starts with `[TeleClaude - Peer (<B TeleClaude session UUID>) · <human display name> · <UTC minute>]`
And the agent segment starts with `[TeleClaude - Peer (<B TeleClaude session UUID>) · <agent runtime>/<thinking mode> · <UTC minute>]`
And every machine-authored segment carries its resolved machine identity rather than being inferred from the user transcript channel
And the full TeleClaude session UUID is rendered in each peer header
And each timestamp comes from the original segment occurrence and renders without seconds or subseconds
And exact timestamp precision remains in transcript and delivery metadata
And no outer peer wrapper surrounds the bundle
And no `--- Human @ ... ---` or `--- Agent @ ... ---` marker is emitted
```

#### UC-DCL3: Agent-harness teammate framing never crosses the link

```
Given an active direct link exists between members A and B
And B's transcript carries an agent-harness teammate-message envelope on the user channel
And B's transcript carries a human-typed turn on the user channel
And B's agent has replied, so neither user-channel turn is the bundle's trailing run
When the cross-delivery collector bundles B's turn for A
Then the teammate-message envelope is excluded from the bundle
And the human-typed turn is delivered
And the envelope is excluded wherever the framing sits in the turn, not only when it opens it
```

```
Given an active direct link exists between members A and B
And the only content in B's transcript since the delivery cursor is an agent-harness teammate-message envelope
When the cross-delivery collector runs for A
Then no bundle is delivered to A
```

#### UC-DCL4: The agent CLI's AGENTS.md instruction injection never crosses the link

```
Given an active direct link exists between members A and B
And B's transcript carries the agent CLI's AGENTS.md instruction injection on the user channel
And B's transcript carries a human-typed turn on the user channel
And B's agent has replied, so neither user-channel turn is the bundle's trailing run
When the cross-delivery collector bundles B's turn for A
Then the instruction injection is excluded from the bundle
And the human-typed turn is delivered under the human marker
And the injection is excluded whether its heading names a directory or stands alone
```

### Cross-context references

- **identity**: caller identity is bound via the caller-session identifier on the request; ignition requires a non-web caller session id (web origins are rejected for `--direct`). The link aggregate stores session ids only; the principal binding is owned upstream by identity.
- **session_subscriptions** (peer feature): the listener axis (one-shot or persistent stop notifications) and the link axis are intentionally orthogonal. While a link is active, listener delivery for the same (caller, target) pair is suppressed at notification time; the listener row is preserved and resumes after closure.
- **conversation_delivery** (peer feature inside agent_runtime): the cross-sharing of turn-complete outputs (per-link cursor advancement, transcript-since-cursor bundling, reconciliation of orphaned pending-through cursors) is invoked at hook-stop and at service startup via the post-adapter completion stage — see the service lifecycle spec.
- **integration**: no direct dependency. Sessions whose initiator/target is an external (non-host-pane) adapter are not eligible for ignition; new-session ignition is only wired from session-spawn paths whose caller is an agent session.

## Known caveats

- **Ignition requires a caller session identity.** Pure web / unidentified callers cannot ignite a link. The link is always between two agent sessions, not a human and a session.
- **Closure is associative, not caller-scoped.** Any member calling `--close-link` severs the link for ALL members. There is no "leave but keep the link alive for the others" path in v1.
- **Reuse short-circuits with an error, not a success.** Calling `--direct` a second time on an already-linked pair returns an error with a rules reminder; the message text is NOT delivered through this path. Members are expected to "just talk" — turn-complete outputs are cross-shared automatically.
- **Plain-send during an active link is rejected.** A non-direct send toward a peer with whom a direct link is active is refused to prevent obfuscating the exchange from observers.
- **Multi-member is structurally supported, not exposed.** The aggregate can represent N>=2 members, and the peer-resolution and delivery paths already fan out N-way; v1 only exposes a two-member direct ignition. Gathering-mode links use the same aggregate.
- **Per-link delivery cursors are anchored at creation, not at first turn.** Pre-link transcript content never appears in the first cross-share. This is the explicit reason the cursors are upserted at ignition rather than lazily at first delivery.
- **Stale duplicate rows are silently healed on next ignition.** If durable storage contains more than one active link for the same pair (e.g., a prior crash mid-creation), the ignition path keeps the first and severs the rest under the canonical pair lock. No external reconciliation pass is needed.
- **Listener rows survive suppression.** Suppression while linked does not remove the listener; once the link severs, the next stop event fires the listener normally. This avoids re-subscription ceremony on every close.
