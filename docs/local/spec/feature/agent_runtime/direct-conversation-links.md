---
description: Bidirectional message routing between two agent sessions via
  the `--direct` ignition flow. A conversation link is established once, peer turn-complete
  outputs are then cross-shared automatically, and `--close-link` severs the link
  for every member.
visibility: public
---

# Direct Conversation Links — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

A **conversation link** is the agent_runtime aggregate that turns two sessions into peers whose subsequent turn-complete outputs are delivered to one another automatically, without re-issuing `telec sessions send` per turn.

The link is established by a single act of _ignition_: any party — typically the caller of `telec sessions send <peer> "<msg>" --direct` — creates the link, the receiving session is added as the second member, and from that moment forward the active-conversation channel supersedes passive listener notifications between the pair. A member severs the link with `--close-link`, which closes it for all members at once; a member whose peer is the orchestrator that dispatched it cannot, because no session acts on the orchestrator that dispatched it (`local/projects/teleclaude/spec/feature/agent_runtime/session-authority`).

The ignition intro carries the shared no-output guidance, so an agent with nothing to add ends its turn without a peer-facing acknowledgement.

The link is an associative aggregate of a link record and its member records, persisted durably by agent_runtime; it survives service restarts and is the canonical record of "these sessions are currently talking to each other."

No link holds two workers: a link whose members include two worker sessions is closed for all of them. Which sessions may ignite or close a link is `local/projects/teleclaude/spec/feature/agent_runtime/session-authority`.

When an opening message has no resolved peer member, it is delivered to the originally addressed target; a resolved member that is missing or closed is skipped.

Each cross-share preserves the source, author, and occurrence time carried by a complete peer envelope and suppresses it only when that source is the destination. The original segment order is retained; a trailing peer segment is not local-human input, and delivery progress is independent of the carried occurrence time and advances only after successful handoff. Other spans remain their source session's content, while control, command-loader, runtime-artifact, and teammate instructions are not forwarded. An unrecognized envelope-like span does not block adjacent content. A turn consisting solely of `NOOP` produces no peer message but still advances its completed-turn position. The sentinel itself never crosses the link (`general/policy/no-output-turn`): a turn that also authored other content shares that content without it. A turn still running when delivery runs is shared only after it completes.

## Canonical fields

### Use cases

#### A person starts a direct conversation with an existing session

```
Given a person asks their agent to start a direct conversation with an existing session
When the agent sends an opening message with `--direct`
Then the target receives the message as a peer contribution
And the sessions become peers whose later turns are shared automatically
```

```gherkin
Scenario: An existing conversation does not accept a third peer
  Given the person's session is already in a direct conversation with another peer
  When they ask to start a direct conversation with a third session
  Then the request is refused with the active peer identified
  And the existing conversation remains unchanged and no new message is sent
  And no new direct conversation is established
```

```gherkin
Scenario: A participant continues an active conversation without re-igniting it
  Given the person's session already shares a direct conversation with the peer
  When they try to send another message with direct ignition
  Then they are told to continue the conversation normally
  And no duplicate link or message is created
```

#### A person starts a new session as a direct conversation peer

```
Given a person asks their agent to start a new session in a direct conversation
When the new session is created with direct ignition
Then it joins the conversation and receives the opening message from its peer
And the listener subscription remains a separate relationship
```

#### UC-DCL22: A person can converse across linked agent sessions

```
Given a person has asked their agent to start a direct conversation with a peer session
When either peer agent completes a turn with conversational content
Then the counterpart session receives the new contribution without the person reissuing a send command
And both agents can continue the same conversation in their respective sessions

Scenario: Rate limiting does not reorder or duplicate peer messages
  Given a person's direct conversation is delivering a multi-part peer turn and the platform rate-limits it
  When deferred messages are delivered or their delivery ultimately fails
  Then delivered messages remain in their original order and appear once
  And an undelivered message has a durable failure outcome

Scenario: A peer message waits for a working agent to yield
  Given a person sends a peer message while their agent is still working
  When the new peer contribution becomes pending
  Then the current work is not interrupted and the agent is told that peer input is pending
  When the agent chooses to yield
  Then it receives the peer contribution as its next input with peer authorship preserved
  And its unfinished work remains available to resume
```

#### UC-DCL1: Peer segments are filtered by original source for each destination

#### UC-DCL17: A third-party peer segment retains its original source

#### UC-DCL18: A trailing peer segment is not held as unanswered local input

#### UC-DCL19: Eligibility is evaluated per peer segment

#### UC-DCL20: Forwarded occurrence time is independent of replay progress

#### UC-DCL21: A person can send local text alongside a peer contribution

```gherkin
Given a person adds local text around a complete peer contribution in one prompt
And another span resembles an envelope but does not form a complete registered one
When the prompt is delivered to the other participant
Then the peer contribution retains its original authorship
And the local and incomplete-envelope-looking text remains the person's content
And all eligible content arrives in order without blocking neighboring text
```

#### UC-DCL24: A person can end the direct conversation for everyone

```
Scenario: Close a direct conversation
  Given a person asks their agent to end a direct conversation it belongs to
  When the agent closes it, optionally with a final message
  Then all members stop cross-sharing turns
  And the final message reaches the peer before closure when one was supplied

Scenario: A child cannot close a conversation with its dispatcher
  Given a person directs an agent to close a conversation with its dispatcher
  When the caller tries to close their direct conversation
  Then the request is refused and the conversation remains open
```

#### UC-DCL2: Cross-delivered segments preserve envelope authorship without a shadow record

#### UC-DCL6: A person can recognize each participant in a direct conversation

```gherkin
Scenario: Peer messages show their original speaker
  Given a direct conversation contains messages from agents and a person
  When the person reads the conversation in Discord
  Then each contribution appears separately and in order under its speaker's resolved identity
  And peer-envelope framing and thinking mode are not shown

Scenario: Adjacent messages from one speaker remain distinct
  Given a peer contributes two consecutive messages
  When the conversation is rendered
  Then each message appears separately in its original order

Scenario: A human speaker remains identifiable without an avatar
  Given a human peer message has no available avatar
  When Discord renders it
  Then the human's display identity remains visible
  And the default avatar does not relabel the speaker as an agent or TeleClaude
```

#### UC-DCL7: Same-author adjacency never merges peer segments into one Discord message

#### UC-DCL8: A human peer segment without an avatar keeps its human identity

#### UC-DCL9: A participant can recognize an original speaker after a peer message is forwarded

```gherkin
Given a person receives a peer contribution forwarded through another session
When they read the contribution
Then it still identifies its original speaker and content
And it is not delivered back to that speaker as a new message
```

#### UC-DCL13: A bare NOOP turn is never cross-shared

#### UC-DCL23: The ignition intro tells a joining peer how to close a turn that owes nothing

#### UC-DCL10: Legacy pre-cutover cursor ranges migrate with durable dispositions

Superseded by the single-registry envelope contract.

#### UC-DCL3: Agent-harness teammate framing never crosses the link

#### UC-DCL4: The agent CLI's AGENTS.md instruction injection never crosses the link

#### UC-DCL11: A freshly ignited link delivers every classified span without recognition failure

#### UC-DCL12: Peer presentation stays ordered and at-most-once under platform rate limiting

#### UC-DCL5: Unrecognized envelope-looking text remains deliverable human input

#### UC-DCL14: A reproduced delimiter in an agent's own turn never re-frames it

#### UC-DCL15: A session already in direct conversation rejects a third peer

#### UC-DCL16: A working peer yields for newly pending peer input

### Cross-context references

- **identity**: caller identity is bound via the caller-session identifier on the request; ignition requires a caller session id. The link aggregate stores session ids only; the principal binding is owned upstream by identity.
- **session_subscriptions** (peer feature): the listener axis (one-shot or persistent stop notifications) and the link axis are intentionally orthogonal. While a link is active, listener delivery for the same (caller, target) pair is suppressed at notification time; the listener row is preserved and resumes after closure.
- **conversation_delivery** (peer feature inside agent_runtime): the cross-sharing of turn-complete outputs (per-link cursor advancement, transcript-since-cursor bundling, reconciliation of orphaned pending-through cursors) is invoked at hook-stop and at service startup via the post-adapter completion stage — see the service lifecycle spec.
- **integration**: no direct dependency. Sessions whose initiator/target is an external (non-host-pane) adapter are not eligible for ignition; new-session ignition is only wired from session-spawn paths whose caller is an agent session.

## Known caveats

- **Ignition requires a caller session identity.** Unidentified callers cannot ignite a link. The link is always between two agent sessions, not a human and a session.
- **Closure is associative, not caller-scoped.** Any member calling `--close-link` severs the link for ALL members. There is no "leave but keep the link alive for the others" path in v1.
- **Reuse short-circuits with an error, not a success.** Calling `--direct` a second time on an already-linked pair returns an error with a rules reminder; the message text is NOT delivered through this path. Members are expected to "just talk" — turn-complete outputs are cross-shared automatically.
- **Plain-send during an active link is rejected.** A non-direct send toward a peer with whom a direct link is active is refused to prevent obfuscating the exchange from observers; no message is delivered through that path, and the link remains open.
- **Exclusivity applies no locality condition, and sees only local link records.** Whether two sessions share a computer is never a reason to accept or refuse a direct link. A third-peer refusal is decided against the link records held by the runtime deciding the request; a conversation recorded on another computer is not visible to that decision. Cross-computer direct establishment remains the pre-existing limitation of the ignition paths, not something this rule narrows or repairs.
- **Multi-member is structurally supported, not exposed.** The aggregate can represent N>=2 members, and the peer-resolution and delivery paths already fan out N-way; v1 only exposes a two-member direct ignition. Gathering-mode links use the same aggregate.
- **Per-link delivery cursors are anchored at creation, not at first turn.** Pre-link transcript content never appears in the first cross-share. This is the explicit reason the cursors are upserted at ignition rather than lazily at first delivery.
- **Stale duplicate rows are silently healed on next ignition.** If durable storage contains more than one active link for the same pair (e.g., a prior crash mid-creation), the ignition path keeps the first and severs the rest under the locks that serialize link establishment. No external reconciliation pass is needed.
- **Listener rows survive suppression.** Suppression while linked does not remove the listener; once the link severs, the next stop event fires the listener normally. This avoids re-subscription ceremony on every close.
