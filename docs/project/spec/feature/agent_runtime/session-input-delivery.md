---
description: 'Delivers operator and orchestrator input (text messages and keystrokes) into running agent sessions via prompt-state delivery and host-pane paste-buffer primitives.'
visibility: 'public'
---

# Session Input Delivery — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The write-side surface that lets operators, orchestrators, and other agents inject input into a running agent session. Two entry shapes share the same host-pane primitive layer:

- **Structured message** — the agent_runtime service resolves the target session, wraps every session-originated payload with a caller-origin identity header, enqueues a `message` command through the command service, and delivers active-agent text through prompt-state user-turn delivery. This is the path the CLI uses for `telec sessions send`. Sessions without an active agent, and headless adoption paths that must recreate a host pane before delivery, use the lower-level paste-buffer primitive directly.

- **Raw key command** — used for special keys (Enter, Backspace, arrow keys, Tab, Ctrl-C, etc.) and key repeats via a count argument; routed through the command mapper / command service.

Both paths use the host-pane orchestration layer's paste/key primitives. Raw key commands invoke the key-injection primitive directly. Active-agent structured messages make one content-independent pre-delivery observation: an empty composer receives one paste-and-submit operation, while a composer containing any input receives exactly two newlines plus the platform text and no Enter. The delivery path never compares, reconstructs, hashes, or searches composer text against the accepted payload. Voice, file, result, widget, and escalate flows live next door but belong to integration/messaging — see "Known caveats".

## Canonical fields

### Use cases

#### Structured message — happy path

```
Given an authenticated caller sends a message to a session with text payload
And the target session exists, is not closed or closing, and has a host pane attached
When the agent_runtime service handles the request
Then the target session is loaded from durable storage
And base message metadata is built
And an origin-wrapping step prepends a caller-origin identity header whenever the send is session-originated (the caller carries a session id) — the caller's real machine role when its session resolves one, otherwise an agent header naming the caller's active agent and session
And a send with no caller session id is genuine human direct input and is delivered unwrapped
And the request is dispatched as a "message" command through the command mapper and command service
And when the target session has an active agent, the command path invokes prompt-state user-turn delivery
And prompt-state user-turn delivery inspects only whether the composer contains any input
And an empty composer receives the text through the ordinary paste-and-submit primitive
And an occupied composer receives exactly two newlines followed by the complete text without Enter
And when the target session has no active agent or requires headless adoption, the command path invokes the lower-level host-pane key-injection primitive
And the service returns a successful work-mode send response
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

```
Given the target session has an active agent
When prompt-state user-turn delivery cannot identify the active composer as empty or occupied
Or the selected host-pane paste or paste-and-submit primitive fails
Then the prompt-state delivery routine returns failure
And the upstream send-message path logs the failure and raises a server-side error to the caller
And the message is not marked delivered by queue workers
```

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

```
Given a message arrives for a session whose lifecycle status is headless
And that session records a resumable agent and a native transcript chain
When the delivery path recreates the host pane and resumes that agent into it
Then the payload is submitted only once the resumed agent's prompt is live
And a resumed agent that never reaches its prompt within the readiness budget fails the delivery instead of submitting the payload into a pane no agent is reading
And that failed delivery is reported through the ordinary delivery-failure path rather than recorded as delivered
And a further message for that session is held until the adoption resolves, instead of reaching the pane before the resumed agent's prompt is live
```

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

<!-- planned:fix-tmux-exit-leads-to-compaction -->
#### UC-SID11: A non-composer interactive screen cannot receive platform input

```gherkin
Given the owning human is viewing a running agent session that shows an interactive screen other than its editable composer
And that screen includes a marker also used by the agent's composer
When asynchronous platform-authored text is ready for delivery
Then the interactive screen remains unchanged and unsubmitted
And delivery waits until the agent-specific complete composer can be identified
```
<!-- /planned:fix-tmux-exit-leads-to-compaction -->

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
- **Gemini `!` escaping is implicit.** When the active agent is Gemini, the key-injection primitive rewrites `!` to `\!` before paste because of a known gemini-cli bug. Other agents pass the payload through unchanged.

- **Origin wrapping identifies every session-originated send.** The wrapping step prepends an identity header to every plain send that carries a caller session id. A caller whose session resolves to a machine role is named by that role — orchestrator, integrator, system, worker, tasker, and job_runner each get their own genuine label. A caller whose session resolves to no machine role, such as a top-level interactive session, is named as an agent and identified by its active agent and session id; it is delivered, not refused. The human whose account the session runs under is lineage, not authorship, and never appears in the header. Only genuine human direct input, which carries no caller session id, is delivered unwrapped. A caller session id that does not resolve to a session at all is refused with an explicit error, because no truthful identity can be composed for it; no fabricated role, agent, or host attribution is ever substituted to force a header.

- **The origin header carries no attribution authority.** The header is what the receiving agent reads; it is not what downstream surfaces attribute from. Authorship for a session-originated send is carried structurally on the accepted row and its transcript binding, so the header can be absent, altered, or imitated without moving attribution.

- **Auto-registered one-shot listener is best-effort.** When a non-self caller with a host pane sends a work-mode message, the agent_runtime service attempts a one-shot listener registration so the caller sees the response. Failures are swallowed at debug and never block delivery.
- **No payload size cap at this layer.** The buffer-load step reads from stdin so the host-pane argument-length limit does not apply, but very large payloads still pay paste-time cost in the agent's terminal renderer.
