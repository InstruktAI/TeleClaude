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

Both paths use the host-pane orchestration layer's paste/key primitives. Raw key commands invoke the key-injection primitive directly. Active-agent structured messages wrap the same paste primitive with prompt-state observation: paste once, wait until effective live input is visible, submit with Enter, and retry only Enter while the input remains stuck. Voice, file, result, widget, and escalate flows live next door but belong to integration/messaging — see "Known caveats".

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
And prompt-state user-turn delivery pastes the text once, waits until effective live input is observed, and submits with Enter
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
When prompt-state user-turn delivery pastes a structured message once
And effective live input is never observed after the paste
Or effective live input remains stuck after the Enter retry budget
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
Then a caller whose session resolves to a machine role — orchestrator, integrator, system, worker, tasker, or job_runner — has its message prepended with a machine-role identity header naming that caller's real role and session
And a caller whose session resolves to no machine role has its message prepended with an agent identity header naming the caller's active agent and session
And a caller whose session does not resolve at all has the send refused with an explicit error, because no truthful identity can be composed for it
And no fabricated role label, and no human identity, is ever substituted to force a header
And in no branch is a session-originated message delivered as human-looking typed input
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

### Cross-context references

- **identity** — the caller-identity context (resolved via clearance for the send/keys flows) gates access; the caller's session id and system role feed origin wrapping.
- **integration** — when the originating user is on an external messaging adapter (Telegram, Web), the message reaches the send flow through the integration adapter; for terminal callers, origin metadata stays in agent_runtime.
- **session_mirrors** — delivered text is captured downstream by the agent's native transcript and eventually extracted to the eternal mirror; this spec covers only the inbound write.
- **session_ledger** — session loading, last-message-sent-at, and lifecycle status ride on session-ledger storage; this spec consumes those fields read-only.

## Known caveats

- **Voice, file, result, widget, escalate are intentionally NOT covered here.** Those flows live adjacent to the input-delivery surface but cross into integration/messaging (adapter delivery, Discord escalation, file storage) and are owned by that context.
- **Direct-link machinery deferred to its own spec.** The work-mode send conflict response and the work-mode auto-listener registration are described here; the create / fan-out / close-link flow has its own feature spec to avoid duplication.
- **No re-paste / no replay on ordinary send failure.** A delivery failure surfaces as a server-side error to the caller. There is no service-side re-paste and no replay on session restart for ordinary work-mode sends — the caller decides whether to retry. Active-agent structured sends, startup `agent_then_message`, and self-restart stimulus paths use prompt-state delivery: paste once, observe the live prompt input, continue observation when the first post-paste window still shows empty/suggestion/chrome, retry only Enter while effective user input remains stuck, and report delivery from the prompt-state transition rather than waiting for `user_prompt_submit`.
- **Single host-pane paste buffer per call.** The key-injection primitive allocates a unique buffer name per call and always attempts cleanup on the way out, even when the paste step failed; a cleanup failure leaves the user payload resident in the host pane's buffer list until the host-pane server exits and is logged at warning.
- **A small post-paste gap is hardcoded for raw key-injection.** The ordering margin between the bracketed-paste close marker and the discrete submit does NOT scale with payload size; resizing this constant affects every raw key-injection send. Prompt-state delivery waits on observed live input before sending Enter instead of relying on that gap.
- **Gemini `!` escaping is implicit.** When the active agent is Gemini, the key-injection primitive rewrites `!` to `\!` before paste because of a known gemini-cli bug. Other agents pass the payload through unchanged.

- **Origin wrapping identifies every session-originated send.** The wrapping step prepends an identity header to every plain send that carries a caller session id. A caller whose session resolves to a machine role is named by that role — orchestrator, integrator, system, worker, tasker, and job_runner each get their own genuine label. A caller whose session resolves to no machine role, such as a top-level interactive session, is named as an agent and identified by its active agent and session id; it is delivered, not refused. The human whose account the session runs under is lineage, not authorship, and never appears in the header. Only genuine human direct input, which carries no caller session id, is delivered unwrapped. A caller session id that does not resolve to a session at all is refused with an explicit error, because no truthful identity can be composed for it; no fabricated role, agent, or host attribution is ever substituted to force a header.

- **Auto-registered one-shot listener is best-effort.** When a non-self caller with a host pane sends a work-mode message, the agent_runtime service attempts a one-shot listener registration so the caller sees the response. Failures are swallowed at debug and never block delivery.
- **No payload size cap at this layer.** The buffer-load step reads from stdin so the host-pane argument-length limit does not apply, but very large payloads still pay paste-time cost in the agent's terminal renderer.
