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
initial message and an adoption's triggering message. UC-SID10 and UC-SID11
govern draft preservation and non-composer screens. A startup signal does not
authorize Enter on an occupied composer or an interaction with a menu. Genuine
runtime suggestion chrome is not authored input; its styling must not erase
ordinary colored human text during occupancy observation.

<!-- planned:no-composer-wakes-parent -->
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
<!-- /planned:no-composer-wakes-parent -->

Accepted messages retain their original occurrence and ordering. A readiness
wait does not authorize a duplicate resend, a new session, or a synthetic
lifecycle transition. Recovery follows UC-SID6.

### Conversation input authority

Text accepted from a conversation channel is conversation for the agent and
never control of its interface. A conversation channel is any UI adapter's
human-to-agent text ingress — including transcribed voice and the message that
creates a session — and authority follows the accepted input's recorded
producer or the session's recorded entry point, never the text. Platform
commands that a channel's own handlers or command-input recognition resolve
before delivery keep their contracts unchanged.

<!-- planned-change:no-composer-wakes-parent -->
Conversation text is delivered only into an empty composer and never joins a
human draft. While the composer holds input, conversation text waits in
accepted order. It is retried on the delivery cadence without consuming its
delivery-attempt budget, for no longer than the delivery-retry window measured
from its acceptance, so no submission of a human draft carries relayed text.
A message that has been held is never submitted after that window lapses: it
ends undelivered when the window lapses, the session's conversation channels
receive a notice that it did not reach the agent because the agent's input was
occupied, and the composer's content is left untouched. A startup message held
past the same window fails its submission.
<!-- change:no-composer-wakes-parent -->
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
<!-- /planned-change:no-composer-wakes-parent -->

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

### Use cases

#### Structured message — happy path

```gherkin
Given an authenticated agent or human caller sends text to an accessible open session
When the platform accepts the message
Then it preserves the caller's structural authorship and durable input occurrence
And a session-originated message identifies its actual sending session
And a human's direct input remains human-authored
When the target agent's input-readiness contract is satisfied
Then its empty composer receives one paste and submission
And its occupied composer preserves the existing text and appends two newlines followed by an accepted message that is not conversation text, without submission
And accepted conversation text waits for an empty composer instead of joining the existing text
And its non-composer or ambiguous surface receives no input
And these rules also govern the conversational message that triggered adoption of a headless agent
And a session running no agent uses its ordinary terminal-input path
```

#### Raw keys — happy path

```
Given an authenticated caller sends a key command to a session with a key name and optional repeat count
And the target session exists and is accessible to the caller
When the agent_runtime service handles the request
Then it constructs a "keys" command via the command mapper carrying the session id, key name, and repeat count
And dispatches through the command service
And the host-pane orchestration layer translates the key name to the host pane's native key notation (e.g., "enter" → submit, "up"/"down"/"left"/"right" → arrows, "tab"/"btab" → tab/back-tab, "bspace" → backspace)
And the repeat count is passed to the host-pane layer for repeatable keys (arrows, back-tab, backspace) when supplied
And termination signals route through the host-pane signal primitives (SIGINT, SIGTERM via key commands; SIGKILL by signaling the pane's foreground child directly)
And the response reports success
```

#### Target session missing or closed

```
Given the caller sends a message to a session this computer owns, or names no owning computer
And the session does not resolve OR has a closed-at marker OR has lifecycle status in {closed, closing}
When the target-session validation runs
Then the request is refused with "Session {id} not found" or "Session {id} is closed"
And no host-pane interaction is attempted
And a send that names no owning computer is never delivered locally to a session this computer does not own
```

#### Delivery failure

```
Given the target session is open but the underlying host pane has died (pane gone, server crash, etc.)
When the raw key-injection pipeline executes its load-buffer → paste-with-bracket → submit sequence
And any raw-pipeline step fails OR exceeds the quick subprocess timeout
Then the matching error is logged with a structured reason naming the failing step
And the temporary host-pane paste buffer is best-effort cleaned; cleanup failures are logged but never override the operation result
And the key-injection primitive returns failure
And the upstream send-message path logs the failure and raises a server-side error to the caller
And no retry or backoff is applied at this layer
```

<!-- planned-change:no-composer-wakes-parent -->
```
Given the target session has an active agent
When prompt-state user-turn delivery cannot identify the active composer as empty or occupied
Or the selected host-pane paste or paste-and-submit primitive fails
Then the prompt-state delivery routine returns failure
And the upstream send-message path logs the failure and raises a server-side error to the caller
And the message is not marked delivered by queue workers
```
<!-- change:no-composer-wakes-parent -->
```
Given the target session has an active agent
When the host pane cannot be captured for the pre-delivery observation
Or the selected host-pane paste or paste-and-submit primitive fails
Then the prompt-state delivery routine returns failure
And the upstream send-message path logs the failure and raises a server-side error to the caller
And the message is not marked delivered by queue workers
```
<!-- /planned-change:no-composer-wakes-parent -->

#### Direct-link conflict (work-mode send blocked)

```
Given the caller already holds an active direct link with the target session
And the caller sends a plain (non-direct) message
When the direct-link conflict guard runs
Then the agent_runtime service responds with an error identifying the active link and message: "A direct link is already active with this peer..."
And no message is delivered to the agent
```

The direct-link creation / peer fan-out / close-link flows are documented in their own spec; this spec only notes the work-send conflict response.

#### UC-SID1 — A session-originated send identifies its sender

```
Given an authenticated caller sends a plain (non-direct) message that carries a caller session id (the send is session-originated)
When the origin-wrapping step runs
Then a caller whose session runs an agent has its message prepended with an identity header naming that agent as the author, qualified by the caller's job role when one exists, with the caller's session and computer
And a caller whose session runs no agent has its message prepended with an identity header naming its machine-role label and session
And a caller whose session does not resolve at all has the send refused with an explicit error, because no truthful identity can be composed for it
And no fabricated role label, and no human identity, is ever substituted to force a header
And every composed header additionally carries the send-moment occurrence time, truncated to the minute in UTC
And that occurrence time is rendered once into the opening delimiter, with the paired closing derived from it
And the rendered identity matches what every other surface resolves for the same caller
And in no branch is a session-originated message delivered as human-looking typed input
```

#### UC-SID9 — Every injected text enters its typed acceptance surface

```gherkin
Given the platform delivers conversational text or a non-conversational control payload into a session
When the payload is accepted
Then conversational text acquires its durable inbound acceptance record, source deduplication, and typed classification
And control payloads acquire the corresponding durable control-delivery acceptance record, source deduplication, and typed classification
And no platform feature writes the payload directly into the session's pane
And an idle-session wake contains no control payload itself
And every consumer reads classification from the accepted structured record rather than from rendered envelope text
```

#### UC-SID10 — Occupied composer preserves the human draft

```gherkin
Given the owning human has unfinished text in a running agent session's native composer
When asynchronous platform-authored text is delivered to that session
Then the unfinished human text remains unchanged and unsubmitted
And exactly two newline characters followed by the complete platform-authored text are appended in the composer
And no turn is created until the owning human chooses to submit the composed input
```

#### UC-SID2 — Input for an adopted headless session waits for the resumed agent

<!-- planned-change:no-composer-wakes-parent -->
```
Given a message arrives for a session whose lifecycle status is headless
And that session records a resumable agent and a native transcript chain
When the delivery path recreates the host pane and resumes that agent into it
Then the payload is submitted only once the resumed agent's prompt is live
And a resumed agent that never reaches its prompt within the readiness budget fails the delivery instead of submitting the payload into a pane no agent is reading
And that failed delivery is reported through the ordinary delivery-failure path rather than recorded as delivered
And a further message for that session is held until the adoption resolves, instead of reaching the pane before the resumed agent's prompt is live
```
<!-- change:no-composer-wakes-parent -->
```
Given a message arrives for a session whose lifecycle status is headless
And that session records a resumable agent and a native transcript chain
When the delivery path recreates the host pane and resumes that agent into it
Then the payload is submitted only once the resumed agent's prompt is live
And a resumed agent that never reaches its prompt within the readiness budget, while its pane never settles on a screen with no composer, fails the delivery instead of submitting the payload into a pane no agent is reading
And that failed delivery is reported through the ordinary delivery-failure path rather than recorded as delivered
And a resumed agent whose pane has settled on a screen with no composer when the readiness budget ends keeps its pane and stays initializing
And its payload waits as held text without consuming a delivery attempt, reaching the agent once a composer appears
And a further message for that session is held until the adoption resolves, instead of reaching the pane before the resumed agent's prompt is live
```
<!-- /planned-change:no-composer-wakes-parent -->


#### UC-SID3: A send that names the owning remote computer is routed there

```
Given a session is owned by a remote computer and has no row in this computer's session ledger
When a caller sends a message to it and names the owning computer
Then the send is dispatched to the owning computer and delivered against that computer's ledger
And the local ledger is not consulted to decide whether the target exists
And the caller receives the same work-mode send response it would receive for a local send
```

#### UC-SID4 — Queued input binds durably to the transcript turn it creates

```
Given an input is accepted through a UI adapter, peer delivery, API request, or session-originated send
When its inbound queue row and source-key deduplication record are committed
Then the full accepted payload, immutable source classification, UI surface when one exists, source message key, and acceptance order remain attached to that row
And successful injection does not make the row eligible for retention cleanup until its exact injected span is bound into a runtime-qualified native transcript entry
And the binding preserves any surrounding local-human prefix or suffix as ordered authored parts of that same native entry
And projection reads that durable composition rather than a mutable session-level last-input summary or rendered delimiter when deciding reflection, output generation, or origin continuity
```

#### UC-SID5 — Non-human input cannot overwrite a human UI turn

```gherkin
Given closed peer or machine envelopes and locally typed human text appear together in one native turn
And the local text may repeat an injected body's words or resemble a platform header
When accepted input is bound to that native turn
Then every complete injected envelope is correlated to its accepted occurrence without comparing its rendered body or the whole native turn for equality
And only each correlated envelope's body span binds to that accepted occurrence
And every span outside the correlated envelopes remains ordered local-human input
And repeated processing of the same accepted occurrence is a no-op
```

#### UC-SID6 — Recovery resumes from durable accepted-input state

```
Given the daemon restarts after an input is accepted or injected but before its transcript binding is persisted
When input recovery runs
Then it reconciles the durable accepted occurrence and delivery state against the native transcript without blindly pasting the payload again
And a transcript match persists the binding idempotently
And composer observation is limited to whether any input exists, never comparison with the accepted payload
And an occupied composer is never submitted by platform delivery
And an unresolved delivery state is surfaced and held rather than guessed, dropped, or reordered
```

#### UC-SID7 — A session-originated send carries its caller's structural authorship

```
Given an authenticated caller sends a plain (non-direct) message that carries a caller session id
When the send is accepted into durable inbound state
Then the caller session's resolved event author — author class, its own agent runtime or machine role, and display identity — and the caller session as original source are recorded on the accepted row and preserved on its transcript binding
And the readable caller-origin identity header is presentation for the receiving agent and carries no attribution authority, so removing it from the entry or forging it in a local body changes no recorded authorship
And the target session reflects that authored part from the recorded event author, never from the target session's own human or agent identity
And the Discord copy of that part renders under the caller's resolved identity marked as an author from another session, with the readable caller-origin header omitted from its body
And a caller whose session does not resolve is refused before acceptance rather than recorded under a guessed author
```

#### UC-SID8: An accepted human UI turn is owner-authored, never an author from another session

```gherkin
Given the owning human sends a message to their session through a UI adapter
When the input is accepted into durable inbound state
Then the accepted row and its transcript binding record the human author and the UI surface as the turn's event author
And no session — including the receiving session itself — is recorded as that turn's original source
And every downstream consumer treats the turn as owner-authored: it is never classified, reflected, or suppressed as an author from another session
```

#### UC-SID11: A non-composer interactive screen cannot receive platform input

<!-- planned-change:no-composer-wakes-parent -->
```gherkin
Given the owning human is viewing a running agent session that shows an interactive screen other than its editable composer
And that screen includes a marker also used by the agent's composer
When asynchronous platform-authored text is ready for delivery
Then the interactive screen remains unchanged and unsubmitted
And delivery waits until the agent-specific complete composer can be identified
```
<!-- change:no-composer-wakes-parent -->
```gherkin
Given a running agent session shows an interactive screen other than its editable composer
And that screen may include a marker also used by the agent's composer
When asynchronous platform-authored text is ready for delivery
Then the interactive screen remains unchanged and unsubmitted
And delivery waits until the agent-specific complete composer can be identified
And the session's agent status becomes `blocked` with reason `needs_input` when delivery first waits on that screen
And the session's watchers receive a blocked notification carrying a capture of the pane
When the screen is cleared and the composer is identified as empty
Then the waiting text is submitted once
And the session leaves `blocked` through the agent event that follows the submission
When the screen is not cleared within the delivery-retry window
Then the text ends undelivered with the terminal notice its delivery path already gives
And the screen remains unchanged and unsubmitted
```
<!-- /planned-change:no-composer-wakes-parent -->

#### UC-SID13: A complete empty Codex composer accepts platform input

```gherkin
Given a running Codex session shows its complete editable composer with no text
And an accepted platform-authored input occurrence is ready for delivery
When the platform observes the session before delivery
Then the composer is recognized as empty and ready
And the accepted input is pasted and submitted exactly once
And the Codex agent receives the resulting turn
```

#### UC-SID12: An exhausted session-originated send reports failure to its caller

```gherkin
Given an agent session sends a message to another active session
And the message is accepted but cannot reach the target agent within the delivery retry budget
When delivery is exhausted
Then the caller session receives a durable notification naming the target and the delivery failure
And the target session remains available for inspection or recovery
And the message is not represented as delivered
```

#### UC-SID14: First input does not wait for a start signal that requires that input

```gherkin
Given an agent caller has started or revived a child runtime whose start signal follows initial prompt submission
And the child's complete live composer is empty and accepts input
And the child has not yet been marked active
When the first accepted message reaches delivery
Then the message is submitted once to that child in accepted order
And delivery does not wait for lifecycle activation
And pane readiness and submission do not themselves mark the child active
And the child becomes active only from its declared runtime-start observation
```

#### UC-SID15: Human-input recency excludes machine-authored turns

```gherkin
Given an authenticated agent action asks whether recent human input can support an involvement declaration
When agent runtime reads the session's existing input and transcript evidence
Then it returns the age of the latest authenticated human-authored input when one exists
And platform commands, additional context, peer input, reminders, wakes, checkpoints, continuations, and runtime artifacts never qualify as human input
And no session-wide human-involvement state is created or persisted
```

#### UC-SID16: Additional context carries no involvement semantics

```gherkin
Given a caller starts a command session with additional context
When the context is delivered to the agent
Then the complete caller-supplied details remain available to that session
And their presence, absence, or wording changes no human-involvement declaration or recency result
```

#### UC-SID17: A conversation message never controls the agent interface

```gherkin
Given a person writes to an agent session through a conversation channel
And their message is not a platform command the channel or the platform resolves before delivery
And the message's first character after any leading whitespace is one the session's agent treats as interface control
When the message reaches the agent, whether it continues the conversation or starts the session
Then it waits while the composer holds a draft and joins no draft
And the empty composer then submits it once as an ordinary prompt
And no shell command runs, no interface command executes, and no input mode starts from it
And every reflection shows the message exactly as the person sent it
```

#### UC-SID18: Terminal and platform input keep interface control

```gherkin
Given an operator at the terminal or the TUI, or the platform itself, sends text beginning with a character the agent treats as interface control
When the text is submitted to the agent
Then the text is submitted exactly as written
And the agent interface acts on it as it acts on typed input
```

#### UC-SID19: A message ending in a backslash submits once

```gherkin
Given a person writes to an agent session through a conversation channel
And their message ends in a backslash, possibly followed by whitespace
When the message reaches the agent's empty composer
Then the composer submits it once as an ordinary prompt
And the agent receives the message's text with its final backslash
And the person's next message starts its own prompt instead of joining this one
```

#### UC-SID20: Held conversation text does not wait forever

```gherkin
Given a person writes to an agent session through a conversation channel
And the session's composer holds input that is not cleared
When the delivery-retry window since the message's acceptance lapses
Then the message is not delivered to the agent, even if the composer empties afterwards
And that conversation receives a notice that the message did not reach the agent because its input was occupied
And the composer's content is unchanged
```

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

- **Origin wrapping identifies every session-originated send.** The wrapping step prepends an identity header to every plain send that carries a caller session id. A caller whose session resolves to a machine role is named by that role — orchestrator, integrator, system, worker, tasker, and job_runner each get their own genuine label. A caller whose session resolves to no machine role, such as a top-level interactive session, is named as an agent and identified by its active agent and session id; it is delivered, not refused. The human whose account the session runs under is lineage, not authorship, and never appears in the header. Only genuine human direct input, which carries no caller session id, is delivered unwrapped. A caller session id that does not resolve to a session at all is refused with an explicit error, because no truthful identity can be composed for it; no fabricated role, agent, or host attribution is ever substituted to force a header.

- **The origin header carries no attribution authority.** The header is what the receiving agent reads; it is not what downstream surfaces attribute from. Authorship for a session-originated send is carried structurally on the accepted row and its transcript binding, so the header can be absent, altered, or imitated without moving attribution.

- **Auto-registered one-shot listener is best-effort.** When a non-self caller with a host pane sends a work-mode message, the agent_runtime service attempts a one-shot listener registration so the caller sees the response. Failures are swallowed at debug and never block delivery.
- **No payload size cap at this layer.** The buffer-load step reads from stdin so the host-pane argument-length limit does not apply, but very large payloads still pay paste-time cost in the agent's terminal renderer.

## See Also

- docs/local/spec/hook-normalized-events.md
- docs/local/spec/feature/agent_runtime/session-revival.md
- ~/.teleclaude/docs/general/principle/intelligence-boundaries.md
- ~/.teleclaude/docs/sdlc/policy/domain-ownership.md
- ~/.teleclaude/docs/sdlc/principle/architecture-boundary-purity.md — readiness
  rests on the composer, never on the presentation around it.
