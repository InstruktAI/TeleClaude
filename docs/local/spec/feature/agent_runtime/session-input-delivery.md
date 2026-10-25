---
description: 'Delivers operator and orchestrator input (text messages and keystrokes) into running agent sessions via prompt-state delivery and host-pane paste-buffer primitives.'
visibility: 'public'
---

# Session Input Delivery — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

The write-side surface that lets operators, orchestrators, and other agents inject input into a running agent session. Two entry shapes share the same host-pane primitive layer:

- **Structured message** — the agent_runtime service resolves the target session,
  preserves caller identity and durable typed acceptance, and delivers agent text
  through the shared occupancy-aware input surface. This includes first input
  after launch and the conversational message that triggers headless adoption.
  Sessions without an agent use the lower-level pane primitive directly;
  adoption uses that primitive for shell and runtime launch only.

- **Raw key command** — used for special keys (Enter, Backspace, arrow keys, Tab, Ctrl-C, etc.) and key repeats via a count argument; routed through the command mapper / command service.

Both paths use the host-pane orchestration layer's paste/key primitives. Raw key commands invoke the key-injection primitive directly. Active-agent structured messages make one content-independent pre-delivery observation: an empty composer receives one paste-and-submit operation, while a composer containing any input receives exactly two newlines plus the platform text and no Enter — except conversation text, which waits for an empty composer (Conversation input authority).
The delivery path never compares, reconstructs, hashes, or searches composer text against the accepted payload. Voice, file, result, widget, and escalate flows live next door but belong to integration/messaging — see "Known caveats".

## Canonical fields

### Startup readiness and lifecycle authority

Human pane inspection, automated input readiness, and runtime lifecycle
activation are independent capabilities. An open bound pane remains inspectable
without either input readiness or runtime activation.

Provider adapters own native startup-event origin, timing, and capabilities.
The input-readiness owner consumes those facts and observes the complete live
composer. Lifecycle coordination records the declared runtime-start fact; it
does not infer composer readiness from the shared normalized event name.

| Runtime           | Startup authority for post-launch first-input delivery                                                    | Lifecycle-start observation                                                |
| ----------------- | --------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| Claude            | Reliable native start signal, followed by ordinary composer protection at delivery                        | Native `SessionStart`                                                      |
| Codex             | Complete live-pane composer readiness; no dependency on the later start hook                              | Native `SessionStart`, deferred until the submitted prompt starts a turn   |
| Antigravity (agy) | Complete live-pane composer readiness                                                                     | First native `PreInvocation`, normalized by the adapter to `session_start` |
| DeepSeek          | Complete live-pane composer readiness; Claude-compatible hook names confer no pre-input startup guarantee | Its declared hook adapter's runtime-start observation                      |

The startup gate applies consistently to fresh sessions, first input accepted
after an empty launch, and resumed or adopted sessions. An initializing
lifecycle does not prevent delivery when the runtime's input-readiness contract
is satisfied. Pane readiness permits input only; it never activates lifecycle.

Live-pane composer readiness rests on settled agent activity: the pane is
assessed for input only after the agent's visible activity has stopped changing
for the readiness quiet window, and the composer decision never restarts that
window. The complete live composer is identified solely by the markers the
agent CLI draws as part of the composer itself — its prompt glyph, the frame,
border, or padding that bounds it, and the input cursor the CLI places in it —
and the empty or occupied decision reads only what those markers enclose. Rows outside the composer, including footers,
status lines, hints, warnings, model and context labels, and animation, are
never read for what they say and never become a candidate composer; changing
them changes neither readiness nor occupancy. A transcript echo of an earlier
prompt is not the live composer.

Headless adoption uses lower-level pane primitives for shell and runtime launch;
its triggering conversational message uses the shared input-delivery surface.
Every post-launch text delivery observes composer occupancy, including the
initial message and an adoption's triggering message. This protects the
person's existing draft and prevents injection into a non-composer screen. A
startup signal does not authorize Enter on an occupied composer or an
interaction with a menu. Genuine runtime suggestion chrome is not authored
input; its styling must not erase ordinary colored human text during occupancy
observation.

When that observation identifies no composer because the agent shows another
screen, nothing is pasted, typed, or submitted into that screen, whatever the
input's authority, and the input reaches the agent only once a later
observation finds an empty composer. Waiting on that screen is not a delivery
failure and consumes no delivery attempt. Queued text of either authority waits
in accepted order for no longer than the delivery-retry window measured from its
acceptance; conversation text then ends as described under Conversation input
authority, and platform-authored text ends undelivered with the terminal notice
its producer receives when its delivery is exhausted. A startup message that
reaches the observation waits for the same window and fails its submission when
it lapses. A pane-readiness wait sees the same screen: a surface with no
composer that has stopped changing for the readiness quiet window counts as
that observation, and the readiness wait keeps its own limit. Queued text that
meets such a readiness limit waits like any other queued text; a headless
adoption whose readiness wait ends on such a screen keeps its pane and stays
initializing, and the waiting text reaches the agent through that session once
a composer appears. The first
observation that finds no composer while the
session is not already `blocked` with reason `needs_input` puts it there, which
wakes its watchers once with a capture of the pane so an agent can clear or
escalate what the screen shows
(`local/projects/teleclaude/spec/feature/agent_runtime/session-subscriptions`);
later observations of the same screen change neither the status nor the
watchers.
A pane that cannot be captured is a delivery failure, not a screen without a
composer.

Accepted messages retain their original occurrence and ordering. A readiness
wait does not authorize a duplicate resend, a new session, or a synthetic
lifecycle transition. After daemon restart, recovery reconciles the durable
accepted occurrence against the native transcript and composer state rather
than pasting blindly; an unresolved delivery remains visible and held rather
than guessed, dropped, or reordered.

### Returning input during idle maintenance

Accepted conversation input remains durable while a temporary compaction
launch is running. Before normal delivery readiness or composer observation,
the conversation runtime abandons that maintenance attempt, discards its tmux
runtime through the existing shutdown path and revives the ordinary agent
from the conversation's recorded transcript. Delivery reads the revived
session afresh and follows its ordinary profile, readiness and queue-ordering
contract. It neither injects visitor input into maintenance nor expires the
input when maintenance is abandoned.

Desk re-entry takes the same runtime-return operation even when it carries no
text to deliver. Multiple returning messages share that operation; they do not
start independent replacements. Cancellation remains reachable during
maintenance instead of waiting for the compaction operation to finish.

An abandoned maintenance launch does not end the conversation. Its later
startup or completion cannot satisfy ordinary input readiness or close the
revived session. Native transcript resumption and tmux process handling keep
their existing contracts.

### Conversation input authority

Text accepted from a conversation channel is conversation for the agent and
never control of its interface. A conversation channel is any UI adapter's
human-to-agent text ingress — including transcribed voice and the message that
creates a session — and authority follows the accepted input's recorded
producer or the session's recorded entry point, never the text. Platform
commands that a channel's own handlers or command-input recognition resolve
before delivery keep their contracts unchanged.

Conversation text is delivered only into an empty composer and never joins a
human draft. While the composer holds input, or while no composer can be
identified because the agent shows another screen, conversation text waits in
accepted order. It is retried on the delivery cadence without consuming its
delivery-attempt budget, for no longer than the delivery-retry window measured
from its acceptance, so no submission of a human draft carries relayed text.
A message that has been held is never submitted after that window lapses: it
ends undelivered when the window lapses, the session's conversation channels
receive a notice that it did not reach the agent because the agent's input was
occupied, and the composer's content and any screen shown in its place are
left untouched. A startup message held past the same window fails its
submission.

When conversation text is submitted to an agent's empty composer and its first
character after any leading whitespace and leading invisible format characters
is one that runtime's composer treats as interface control, the runtime's
neutralizing mark is placed at the very start of the text. When its last
character other than trailing whitespace is a backslash and that runtime's
composer would turn the submitting Enter into a line continuation, the
runtime's trailing mark is placed at its end. The text is otherwise submitted
unchanged. Each runtime's control characters, its neutralizing mark — a
character that makes the composer treat the text as an ordinary prompt and
submit it on the single discrete Enter — and its trailing mark, if any, are
declared once on its canonical agent entry
(`local/projects/teleclaude/spec/feature/agent_runtime/agent-vocabulary`), so a
supported runtime without a declaration cannot exist.

Input a person enters at the terminal or the TUI, including what the TUI and
the `telec` CLI send through the platform's API, and platform-authored text —
envelopes, command loaders, continuations — keep full interface control and are
submitted as written. The platform's API is a local socket that records
terminal origin; a conversation channel delivers through its own adapter
ingress, which records the channel.

The platform never alters transcript or prompt-hook text to remove the mark; a
runtime records it or drops it. Accepted-input correlation recognizes a
conversation turn in either form, and the projection of a correlated turn shows
the accepted text
(`local/projects/teleclaude/design/architecture/conversation-delivery`).

### Target validation and delivery outcomes

A target that does not exist, is closed or closing, or is not accessible is
refused before host-pane interaction. Raw-key and direct-send failures return a
caller-visible failure; temporary paste buffers are cleaned on a best-effort
basis, and these direct operations are not retried here. Queue-backed input is
not marked delivered until its accepted occurrence is bound to the native
transcript. If a session-originated send exhausts its delivery window, its caller
receives the target and failure outcome while the target remains available for
inspection or recovery.

### Raw-key commands

Raw-key commands accept named special keys and an optional repeat count for the
keys that support repetition. Host-pane key encoding remains with
`local/projects/teleclaude/spec/feature/agent_runtime/tmux-pane-orchestration`;
raw keys do not use the structured-message composer path.

`enter` submits; `up`, `down`, `left`, and `right` send arrows; `tab`, `btab`,
and `bspace` send Tab, Backtab, and Backspace. Repeat counts apply to arrows,
Backtab, and Backspace. SIGINT and SIGTERM reach the pane as Ctrl-C and Ctrl-\;
SIGKILL keeps the host-pane owner's foreground-child behavior.

### Use cases

#### Structured message — happy path

```gherkin
Scenario: A person sends input to an accessible session through their assistant
  Given a person asks their assistant to send a message to an accessible open session
  When the receiving agent is ready for input
  Then it receives the accepted message once
```

#### Raw keys — happy path

```gherkin
Scenario: An operator sends a key to an accessible session
  Given an operator needs to send a special key to an agent session
  When they send a supported key with an optional repeat count
  Then the session receives that key and reports whether delivery succeeded
```

#### Direct-link conflict (work-mode send blocked)

The direct-conversation-links owner defines the plain-send refusal while a link is active; this surface reports that refusal without delivering the message.

#### UC-SID1 — A session-originated send identifies its sender

#### UC-SID9 — Every injected text enters its typed acceptance surface

#### UC-SID10 — Occupied composer preserves the human draft

```gherkin
Given the owning human has unfinished text in a running agent session's native composer
When asynchronous platform-authored text is delivered to that session
Then the unfinished human text remains unchanged and unsubmitted
And exactly two newline characters followed by the complete platform-authored text are appended in the composer
And no turn is created until the owning human chooses to submit the composed input
```

#### UC-SID2 — Input for an adopted headless session waits for the resumed agent

#### UC-SID3: A send that names the owning remote computer is routed there

#### UC-SID4 — Queued input binds durably to the transcript turn it creates

#### UC-SID5 — Non-human input cannot overwrite a human UI turn

#### UC-SID6 — Recovery resumes from durable accepted-input state

#### UC-SID7 — A session-originated send carries its caller's structural authorship

#### UC-SID8: A person's UI message remains their own

```gherkin
Given a person sends text to their assistant through a UI adapter
When the message is delivered and shown in the conversation
Then it remains attributed to the person who sent it
And no session is presented as the message's original author
```

#### UC-SID11: A non-composer interactive screen cannot receive platform input

#### UC-SID13: A complete empty Codex composer accepts platform input

#### UC-SID12: A person's agent learns when its session message cannot be delivered

```gherkin
Given a person asks their agent to send a message to another active session
And the accepted message cannot reach the target within the delivery window
When delivery ends
Then the caller's session receives a durable failure naming the target
And the target remains available for inspection or recovery
And the message is not represented as delivered
```

#### UC-SID14: First input does not wait for a start signal that requires that input

#### UC-SID15: Human-input recency excludes machine-authored turns

#### UC-SID16: Additional context carries no involvement semantics

#### UC-SID17: A person's conversation message cannot control the agent interface

```gherkin
Given a person sends ordinary conversation text that begins with a character their agent treats as interface control
When the message is delivered to the agent
Then it is submitted as an ordinary prompt rather than running an interface command
And it waits for an empty composer without joining a human draft
And the conversation reflects the person's text as sent
```

#### UC-SID18: An operator can submit interface-control text as typed input

```gherkin
Given an operator enters interface-control text at the terminal or TUI
When the text is submitted to the agent session
Then the text is submitted exactly as written
And the agent interface acts on it as if the operator typed it directly
```

#### UC-SID19: A message ending in a backslash submits once

#### UC-SID20: Held conversation text does not wait forever

#### UC-SID21: Graceful shutdown settles input delivery and its acknowledgment

Graceful settlement is owned by
`local/projects/teleclaude/spec/feature/agent_runtime/daemon-lifecycle`; abrupt-loss
recovery continues to use this surface's durable accepted-input evidence.

#### UC-SID22: A session-originated start message identifies its sender

### Cross-context references

- **identity** — the caller-identity context (resolved via clearance for the send/keys flows) gates access; the caller's session id and system role feed origin wrapping.
- **integration** — when the originating user is on an external messaging adapter (Telegram, Web), the message reaches the send flow through the integration adapter; for terminal callers, origin metadata stays in agent_runtime.
- **session_mirrors** — delivered text is captured downstream by the agent's native transcript and eventually extracted to the eternal mirror; this spec covers only the inbound write.
- **session_ledger** — session loading, last-message-sent-at, and lifecycle status ride on session-ledger storage; this spec consumes those fields read-only.

## Known caveats

- **Voice, file, result, widget, escalate are intentionally NOT covered here.** Those flows live adjacent to the input-delivery surface but cross into integration/messaging (adapter delivery, Discord escalation, file storage) and are owned by that context.
- **Direct-link machinery deferred to its own spec.** The work-mode send conflict response and the work-mode auto-listener registration are described here; the create / fan-out / close-link flow has its own feature spec to avoid duplication.

- **Recovery never means blind re-paste.** A direct send that fails before durable acceptance still reports failure for the caller to retry. Once a queue-backed input is accepted, restart reconciliation uses its durable row, live prompt observation, and runtime-qualified transcript binding to continue or confirm the same occurrence without pasting the payload twice.

- **Single host-pane paste buffer per call.** The key-injection primitive allocates a unique buffer name per call and always attempts cleanup on the way out, even when the paste step failed; a cleanup failure leaves the user payload resident in the host pane's buffer list until the host-pane server exits and is logged at warning.
- **A small post-paste gap is hardcoded for paste-and-submit.** The ordering margin between the bracketed-paste close marker and the discrete submit does NOT scale with payload size; resizing this constant affects every submitted paste. Prompt-state delivery selects that primitive only after its pre-delivery observation finds an empty composer.
- **The host-pane primitives pass text through unchanged.** They paste the payload they receive for every runtime; the characters a delivery adds are the marks described under Conversation input authority, chosen before the primitive is reached.

<!-- planned-change:agent-input-identity-envelope -->

- **Origin wrapping identifies every session-originated send.** The wrapping step prepends an identity header to every plain send that carries a caller session id. A caller whose session runs an agent is named by that agent as the author, qualified by the caller's role name when one exists; a caller whose session runs no agent is named by its role's header label from the agent role catalog (`local/projects/teleclaude/spec/feature/identity/agent-roles`), drawn from the closed label vocabulary. The role is read from the session record's single role field; authorship on the accepted row is unchanged. A caller whose session resolves to no machine role, such as a top-level interactive session, is named as an agent and identified by its active agent and session id; it is delivered, not refused. Session-originated startup messages use the same sender identity; command-dispatched startup input keeps its command form. The human whose account the session runs under is lineage, not authorship, and never appears in the header. Only genuine human direct input, which carries no caller session id, is delivered unwrapped. The carried caller session is taken as given and read from this computer, where the caller runs; no fabricated role, agent, or host attribution is ever substituted to force a header.

<!-- change:agent-input-identity-envelope -->

- **Origin wrapping identifies every agent-originated message.** One wrapping step prepends an identity header to every message an agent sends into a session or starts one with: a plain send, a session start message, the final message of a direct link's close, and a personal assistant's opening brief. A caller whose session runs an agent is named by that agent as the author, qualified by the caller's role name when one exists; a caller whose session runs no agent is named by its role's header label from the agent role catalog (`local/projects/teleclaude/spec/feature/identity/agent-roles`), drawn from the closed label vocabulary. The role is read from the session record's single role field; authorship on the accepted row is unchanged. A caller whose session resolves to no machine role, such as a top-level interactive session, is named as an agent and identified by its active agent and session id; it is delivered, not refused. Command-dispatched startup input keeps its command form. The human whose account the session runs under is lineage, not authorship, and never appears in the header. An agent running outside the platform carries the headless session the platform keeps for it as its caller session (`local/projects/teleclaude/spec/identity-and-auth`, §6), so its messages are wrapped as that session's. Only genuine human direct input, which carries no caller session id, is delivered unwrapped. The carried caller session is taken as given and read from this computer, where the caller runs; no fabricated role, agent, or host attribution is ever substituted to force a header.

<!-- /planned-change:agent-input-identity-envelope -->

- **The origin header carries no attribution authority.** The header is what the receiving agent reads; it is not what downstream surfaces attribute from. Authorship for a session-originated send is carried structurally on the accepted row and its transcript binding, so the header can be absent, altered, or imitated without moving attribution.

<!-- planned-change:agent-input-identity-envelope -->

- **Auto-registered one-shot listener is best-effort.** When a non-self caller with a host pane sends a work-mode message, the agent_runtime service attempts a one-shot listener registration so the caller sees the response. Failures are swallowed at debug and never block delivery.

<!-- change:agent-input-identity-envelope -->

- **Auto-registered one-shot listener is best-effort.** When a non-self caller session that receives control delivery sends a work-mode message, the agent_runtime service attempts a one-shot listener registration so the caller sees the response. A host pane is not required: the response reaches the caller through control delivery (`local/projects/teleclaude/spec/feature/agent_runtime/control-delivery`), so the headless session of an agent running outside the platform hears back like any other caller. Failures are swallowed at debug and never block delivery.

<!-- /planned-change:agent-input-identity-envelope -->

- **No payload size cap at this layer.** The buffer-load step reads from stdin so the host-pane argument-length limit does not apply, but very large payloads still pay paste-time cost in the agent's terminal renderer.

## See Also

- docs/local/spec/hook-normalized-events.md
- docs/local/spec/feature/agent_runtime/session-revival.md
- ~/.teleclaude/docs/general/principle/intelligence-boundaries.md
- ~/.teleclaude/docs/sdlc/policy/domain-ownership.md
- ~/.teleclaude/docs/sdlc/principle/architecture-boundary-purity.md — readiness
  rests on the composer, never on the presentation around it.
