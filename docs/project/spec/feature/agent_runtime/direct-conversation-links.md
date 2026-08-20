---
description: Bidirectional message routing between two (or more) agent sessions via
  the `--direct` ignition flow. A conversation link is established once, peer turn-complete
  outputs are then cross-shared automatically, and `--close-link` severs the link
  for every member.
visibility: public
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

#### UC-DCL1: Peer segments are filtered by original source for each destination

```
Given an active direct link exists between members A and B
And B's transcript contains a canonical peer segment whose original source session is A
And B's transcript contains an orchestrator-authored segment local to B
When the cross-delivery collector bundles B's turn for A
Then the A-origin peer segment is suppressed
And the orchestrator segment is delivered as a real B-origin segment
And no A-to-B-to-A echo segment is produced
```

```
Given B's transcript contains a canonical peer segment whose original source session is C
And the segment was authored by the same human who participates in A and B
When the cross-delivery collector bundles B's turn for A
Then the C-origin segment remains eligible
And its complete original peer header and body are preserved
And human identity does not cause the segment to be suppressed or reassigned to B
```

```
Given a C-origin peer segment is the last visible user-channel segment in B's transcript
And B's turn-complete delivery runs for A
When the collector applies unanswered-turn handling
Then the C-origin segment is not treated as a locally-authored human turn
And it remains eligible without waiting for later local activity in B
```

```
Given one peer bundle in B's transcript contains an A-origin segment followed by a C-origin segment
When the cross-delivery collector bundles B's turn for A
Then eligibility is evaluated for each embedded segment
And the A-origin segment is suppressed
And the C-origin segment remains in its original order with its original attribution
```

```
Given a C-origin peer segment carries original occurrence time C1 in its canonical header
And B recorded the containing transcript entry at replay time B1
When B cross-delivers that segment to A
Then the rendered segment retains occurrence time C1
And B-to-A pending bounds, delivery cursors, and deterministic dedupe use B1
And the inner header time is never used as the replay progress clock
```


```
Given a human has local text before an appended structured peer block in one native prompt
And the human may add more local text after the unchanged peer block before submitting
When the resulting native user entry is bound
Then its ordered authored parts preserve the local-human prefix, peer-authored part, and local-human suffix
And the peer part is rendered for the agent with a readable opening header and `[/TeleClaude - Peer]` closing footer
And the surrounding local text remains attributed to the human in the viewing session
And the rendered delimiters are never parsed to establish the boundary or authorship
And an altered or ambiguous injected peer span surfaces an input conflict instead of guessed attribution
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

#### UC-DCL2: Cross-delivered segments preserve provenance and agent-facing rendering

```
Given an active direct link exists between sessions A and B
And one outbound structured bundle from B contains a role-authored segment, a human-authored segment, and an agent-authored segment
When the conversation-delivery pipeline accepts and renders the bundle for A
Then every segment retains its stable segment ID, original source session, occurrence time, body, and immutable event author
And every readable peer opening header and closing footer is derived from those fields for the agent-facing transcript
And neither rendered delimiter is parsed to recover identity, boundaries, or loop-prevention state
And no outer peer wrapper or generic inner author marker is emitted
```

#### UC-DCL6: Discord renders each peer segment as its own message under the author's aliased identity and avatar

```
Given an accepted structured peer bundle contains a Codex-authored segment, a human-authored segment, and a role-bearing Claude segment in that order
And the bundle is projected into session A's Discord thread
When Discord delivery resolves presentation relative to A
Then it receives three ordered webhook messages containing only the respective bodies
And their aliases are `Codex (peer)`, `<human display name> (peer)`, and `Claude - <raw JobRole> (peer)`
And each message carries its resolved avatar without exposing the readable peer header or footer as Discord copy
And thinking mode does not appear in any Discord alias
And body-free structured logs identify the source session, segment ordinal, alias, avatar selection, target thread, operation, result, and platform message ID
```

#### UC-DCL7: Same-author adjacency never merges peer segments into one Discord message

```
Given an accepted peer bundle contains two eligible Gemini-authored segments
When Discord renders the reflected conversation
Then each segment becomes a distinct ordered Discord message under the Gemini alias and avatar
And same-author adjacency does not merge segment bodies into one Discord message
```

#### UC-DCL8: A human peer segment without an avatar keeps its human identity

```
Given a human-authored peer segment has an original human display identity but no available avatar URL
When Discord renders that reflected segment
Then the human display identity remains the webhook alias
And the message may use the webhook default avatar
But it is not relabelled as TeleClaude, the intermediary session, or an agent
```

#### UC-DCL9: Multi-hop forwarding preserves the original source and suppresses echo

```
Given session B receives an A-origin segment and later forwards its turn to C
When B-to-C delivery runs
Then the forwarded segment retains A as its structured original source
And C sees the original author and occurrence time
And any later delivery toward A suppresses that segment by structured source identity
And no intermediary header parsing participates in the decision
```

#### UC-DCL13: A bare NOOP turn is never cross-shared

```
Given an active direct link exists between members A and B
And member A completes a turn whose entire turn-complete output is the sentinel `NOOP`
When the cross-delivery collector bundles A's turn for B
Then no segment is delivered to B for that turn
And the (link, A→B) delivery cursor still advances past the turn
And A's transcript retains the `NOOP` turn as source truth
```

#### UC-DCL10: Legacy pre-cutover cursor ranges migrate with durable dispositions

```
Given an active legacy direction has a cursor before the structured-delivery cutover
When cutover migration processes that direction
Then every reachable legacy entry receives a durable migrated or recovery disposition
And a frozen active range is rebuilt from transcript truth and delivered exactly once
And compatibility recognition remains limited to evidenced pre-cutover entries until no such cursor range remains
And no cursor is silently promoted or abandoned
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


#### UC-DCL11: A freshly ignited link delivers the peer's first turn without silent stall

```gherkin
Given a direct link is ignited between two live sessions
When the peer completes its first turn after ignition
Then every eligible segment of that turn is delivered to the counterpart session in order
And a segment the delivery path cannot process receives a bounded, durable disposition with an explicit error record instead of being retried without limit
And a delivery direction whose cursor cannot advance surfaces that condition as an explicit error
And no direction of the link stalls silently while its counterpart direction continues to flow
```

#### UC-DCL12: Peer presentation stays ordered and at-most-once under platform rate limiting

```gherkin
Given Discord rate-limits deliveries while a multi-segment peer turn is being presented
When deferred deliveries later succeed
Then the segments appear in their original order
And no segment is presented more than once, however many retries its delivery needed
And a segment whose delivery ultimately fails receives a durable disposition instead of an unbounded retry
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
