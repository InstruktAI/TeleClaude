---
description: "Delivers operator and orchestrator input (text messages and keystrokes) into running agent sessions via the agent_runtime service's host-pane paste-buffer pipeline."
visibility: 'public'
---

# Session Input Delivery — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The write-side surface that lets operators, orchestrators, and other agents inject input into a running agent session. Two entry shapes share the same downstream host-pane pipeline:

- **Structured message** — the agent_runtime service resolves the target session, optionally wraps the payload with a caller-origin header (machine roles only), enqueues a `message` command through the command service, and ultimately delivers the text to the agent's host pane via the paste-buffer pipeline. This is the path the CLI uses for `telec sessions send`.
- **Raw key command** — used for special keys (Enter, Backspace, arrow keys, Tab, Ctrl-C, etc.) and key repeats via a count argument; routed through the command mapper / command service.

Both paths converge on the host-pane orchestration layer's key-injection primitive, which speaks the host pane's bracketed-paste pipeline so multi-line payloads land as a single bracketed-paste event and are submitted with one Enter. Voice, file, result, widget, and escalate flows live next door but belong to integration/messaging — see "Known caveats".

## Canonical fields

### Use cases

#### Structured message — happy path

```
Given an authenticated caller sends a message to a session with text payload
And the target session exists, is not closed or closing, and has a host pane attached
When the agent_runtime service handles the request
Then the target session is loaded from durable storage
And base message metadata is built
And an origin-wrapping step prepends a machine-role identity header iff the caller's session has a system role in {Orchestrator, Integrator, System}
And the request is dispatched as a "message" command through the command mapper and command service
And the command path eventually invokes the host-pane key-injection primitive
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
Given the caller sends a message to a session
And the session does not resolve OR has a closed-at marker OR has lifecycle status in {closed, closing}
When the target-session validation runs
Then the request is refused with "Session {id} not found" or "Session {id} is closed"
And no host-pane interaction is attempted
```

#### Host-pane pipeline failure

```
Given the target session is open but the underlying host pane has died (pane gone, server crash, etc.)
When the key-injection pipeline executes its load-buffer → paste-with-bracket → submit sequence
And any step fails OR exceeds the quick subprocess timeout
Then the matching error is logged with a structured reason naming the failing step
And the temporary host-pane paste buffer is best-effort cleaned; cleanup failures are logged but never override the operation result
And the key-injection primitive returns failure
And the upstream send-message path logs the failure and raises a server-side error to the caller
And no retry or backoff is applied at this layer
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

### Cross-context references

- **identity** — the caller-identity context (resolved via clearance for the send/keys flows) gates access; the caller's session id and system role feed origin wrapping.
- **integration** — when the originating user is on an external messaging adapter (Telegram, Web), the message reaches the send flow through the integration adapter; for terminal callers, origin metadata stays in agent_runtime.
- **session_mirrors** — delivered text is captured downstream by the agent's native transcript and eventually extracted to the eternal mirror; this spec covers only the inbound write.
- **session_ledger** — session loading, last-message-sent-at, and lifecycle status ride on session-ledger storage; this spec consumes those fields read-only.

## Known caveats

- **Voice, file, result, widget, escalate are intentionally NOT covered here.** Those flows live adjacent to the input-delivery surface but cross into integration/messaging (adapter delivery, Discord escalation, file storage) and are owned by that context.
- **Direct-link machinery deferred to its own spec.** The work-mode send conflict response and the work-mode auto-listener registration are described here; the create / fan-out / close-link flow has its own feature spec to avoid duplication.
- **No retry / no replay on ordinary host-pane send failure.** A pipeline failure surfaces as a server-side error to the caller. There is no service-side retry, no queued redelivery, and no replay on session restart for ordinary work-mode sends — the caller decides whether to retry. The startup `agent_then_message` and self-restart stimulus paths use a separate prompt-state delivery routine that pastes once, observes the live prompt input, retries only Enter while effective user input remains stuck, and reports delivery from the prompt-state transition rather than waiting for `user_prompt_submit`.
- **Single host-pane paste buffer per call.** The key-injection primitive allocates a unique buffer name per call and always attempts cleanup on the way out, even when the paste step failed; a cleanup failure leaves the user payload resident in the host pane's buffer list until the host-pane server exits and is logged at warning.
- **A small post-paste gap is hardcoded.** The ordering margin between the bracketed-paste close marker and the discrete submit does NOT scale with payload size; resizing this constant affects every send.
- **Gemini `!` escaping is implicit.** When the active agent is Gemini, the key-injection primitive rewrites `!` to `\!` before paste because of a known gemini-cli bug. Other agents pass the payload through unchanged.
- **Machine-origin wrapping is opt-in by role.** The wrapping step only prepends a header when the caller session has a system role in {Orchestrator, Integrator, System}. Workers and humans send unwrapped text; their identity is conveyed through the Peer bracket upstream or carried by the integration adapter.
- **Auto-registered one-shot listener is best-effort.** When a non-self caller with a host pane sends a work-mode message, the agent_runtime service attempts a one-shot listener registration so the caller sees the response. Failures are swallowed at debug and never block delivery.
- **No payload size cap at this layer.** The buffer-load step reads from stdin so the host-pane argument-length limit does not apply, but very large payloads still pay paste-time cost in the agent's terminal renderer.
