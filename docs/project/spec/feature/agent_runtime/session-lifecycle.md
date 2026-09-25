---
description: agent_runtime — start, list, and end agent sessions. The creation, enumeration,
  and explicit-termination surface that operators and other agents use.
visibility: public
---

# Session Lifecycle — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

The surface for managing the live dimension of an `agent_runtime` Session: creating one (allocating a session id, an associated host pane, and a principal binding), listing what currently exists (subject to role-based visibility), and explicitly ending one (a request to transition to `closed`).

Three operations form the surface: create-session, list-sessions, and end-session. The TUI invokes them via the `telec sessions start`, `telec sessions list`, and `telec sessions end` CLI verbs respectively. Local creation is backed by the in-process command service; remote creation dispatches a new-session request to the target computer and returns the peer-owned session transport fields.

Termination accepted by the service is a request, not a finished close: the end-session call is accepted asynchronously and delegates the actual cleanup to the cleanup module (see `session-cleanup-and-reaping`). The `agent_runtime.session.started` event is emitted when the session has booted; consumers subscribe to that to learn when the new session is live.

## Canonical fields

### Use cases

#### Creating a session — happy path

```
Given an authenticated caller has clearance to start sessions
And the request carries an `origin` (terminal) and an enabled `agent`
When the caller asks the agent_runtime service to create a session with project_path, agent, thinking_mode, launch_kind
Then a session id is generated (or accepted from the command when pre-supplied)
And a host-pane reference is composed using the TeleClaude prefix and the session id
And the session row is recorded in storage with `lifecycle_status="initializing"` and a complete payload (computer name, title, project path, subdir, working slug, human email, human role, principal, active agent, thinking mode)
And host-pane creation and agent CLI launch are kicked off asynchronously by the bootstrap task (not on the request path)
And the response carries the session id, host-pane reference, and the resolved agent
And the `agent_runtime.session.started` event is published when the session is live
```

#### UC-SL2: Principal binding from identity

```
Given the request supplies terminal origin metadata (email payload)
When the agent_runtime service resolves identity via the identity resolver
Then human_email and human_role are populated from the identity context when not explicitly provided
And when an initiator session id references a parent session, missing fields (human_email, human_role, principal) are inherited from the parent
And a session creation without any resolved human_role AND no system role is rejected — the request is refused
```

#### UC-SL20: Single-user terminal caller resolves to admin

```
Given the daemon is in single-user mode
And the request carries no explicit human_role
When a terminal caller POSTs to /sessions
<!-- planned-change:cli-actions-authorize-in-process -->
Then the session record's human_role is admin, resolved by the auth layer (verify_caller), not by a model default
<!-- change:cli-actions-authorize-in-process -->
Then the session record's human_role is admin, taken from the caller identity the request carries, not by a model default
<!-- /planned-change:cli-actions-authorize-in-process -->
```

#### UC-SL21: Restricted role is jailed to the help-desk

```
Given the request carries a non-admin human_role and no system_role
When the session is created
Then the session's project_path is confined to the computer's help-desk directory
```

#### Computer routing

```
Given the request specifies `computer = <remote>`
When the local agent_runtime service receives the create-session request
Then it dispatches a new-session request to the target computer over the inter-computer transport
And the dispatch forwards the initiating client's resolved origin and identity (human_email, human_role, system_role, job) in the command payload so the target's identity gate passes; the originating computer travels separately as the transport initiator, never as origin
And the target agent_runtime service creates the session on its own host-pane layer
And the response carries the remote session id, host-pane reference, computer reference, and resolved agent
And if the target returns an error envelope, an upstream error is surfaced
And if the target does not respond, a timeout error is surfaced
```

#### UC-SL24: Startup message is accepted by the live prompt

```gherkin
Given an agent caller creates a fresh child with an initial message delivered after launch
When the child's startup input-readiness contract is satisfied
Then the accepted message is delivered through the shared occupancy-aware input surface
And an empty composer receives one paste and submission
And an occupied composer preserves existing text and appends the message without submission
And an ambiguous or non-composer screen receives no input
And submission does not itself establish lifecycle activation
```

#### UC-SL25: Startup message enter retries do not re-paste

#### UC-SL26: Historical prompt text does not establish startup readiness

```gherkin
Given an agent caller has an accepted startup message waiting for delivery
And historical terminal output contains an earlier composer
And the current terminal surface is not a complete editable composer
When startup input readiness is assessed
Then the historical composer does not establish readiness
And no message is pasted or submitted on that evidence
```

#### Initiator listener registration

```
Given the caller's session has an initiator session id
And the listener-skip flag is false
When the new session row is created
Then a stop-listener is registered tying caller -> new session
And the caller's host-pane reference is captured so completion notifications can route back
And if the caller has no host pane, registration is skipped with a debug log
```

#### Listing sessions — caller-scoped default

```
Given the TUI lists sessions without `?all=true`
And the request carries the caller-session-id header
When list-sessions runs
Then local sessions are loaded via the local command handler
And cached remote sessions are merged in by session id (local wins on conflict)
And the merged list is filtered to entries whose initiator session id matches the caller-session-id header
And optional `job` filter narrows further
And the human display name is enriched from the people configuration for each entry whose email matches
```

#### UC-SL22: Listing closed sessions — agent status projection

```
Given list-sessions is called with closed sessions included
And a returned session has lifecycle status `closing` or `closed`
Or the returned session carries a `closed_at` marker
When the list response snapshot derives its `agent_status`
Then the terminal lifecycle marker is authoritative over activity timestamps
And the snapshot reports `agent_status="idle"` even when `last_agent_stop_at` is missing
And the snapshot still preserves the lifecycle `status` field as `closing` or `closed`
```


#### UC-SL31: A listed session carries the address of its own conversation

```gherkin
Given an agent lists sessions
And a listed session has a conversation whose address resolves
When the listing answer is returned
Then that session's entry carries the address of its own conversation
And that address opens the same conversation as the backlink already appended to outbound messages originating from that session
```

#### UC-SL32: A session whose address does not resolve is listed without one

```gherkin
Given an agent lists sessions
And a listed session has no conversation whose address resolves
When the listing answer is returned
Then that session's entry carries no address
And no placeholder, empty value, or unopenable address stands in its place
And the rest of that entry is unchanged
```


#### UC-SL23: Only the declared runtime-start boundary establishes liveness

```gherkin
Given an orchestrating agent has started a non-headless child session
And the child runtime has not announced its declared start boundary
When the orchestrating agent reads the child session
Then the child is reported as initializing with unknown agent activity
And session creation, launch delivery, host-pane readiness, host-pane changes, generic timestamps, and other runtime activity do not report it live
When the child runtime announces its declared start boundary
Then the child is reported live and remains supervised
And headless or terminal sessions are not reactivated
```

#### UC-SL29: A silent in-turn session derives stalled

```
Given a non-terminal session whose latest input arrived after its latest authoritative idle boundary
And the session's observed activity has not advanced for longer than the platform's stall threshold
When a projection derives the session's `agent_status`
Then it reports `stalled` instead of `active`
And any subsequent observed activity makes the same derivation report `active` again
And a session within the stall threshold continues to report `active`
And the authoritative-idle, terminal-lifecycle, and no-activity rules remain unchanged
```


<!-- planned:fix-agent-sessions-silently-blocked-on-directory-trust -->

#### UC-SL28: A session is never presented as an active agent while its agent CLI is still gated

```
Given a session is about to launch an agent CLI in a working directory that resolves under a configured trusted root
When agent_runtime dispatches the agent command
Then the agent's own directory-trust state is consulted using that agent's documented resolution rules
And a trust decision the human already made for a configured root is carried forward to that agent wherever the agent supports being written to, so the CLI starts without presenting its directory-trust gate
And a trust store that publishes no supported write surface is left untouched, and the unsatisfied gate is recorded as structured evidence naming the session, the agent, and the directory
And a working directory resolving under no configured trusted root has no trust store consulted for a write, none modified, and the refusal recorded
And until an activity hook proves the agent live, the session reports `lifecycle_status="initializing"` with derived `agent_status` `unknown`
And host-pane output alone never raises that projection to `active`
```

<!-- /planned:fix-agent-sessions-silently-blocked-on-directory-trust -->

#### UC-SL33: A completed native command leaves the agent idle

```gherkin
Given a non-terminal agent session accepts a human operator command through its native CLI
And the native CLI completes the command without starting an agent turn
When an orchestrating agent reads the session's agent status
Then the session reports idle
And the accepted input remains visible in the session record
And a silent agent turn still reports stalled after the platform's stall threshold
```

#### UC-SL34: Failed automatic restoration reaches an owned terminal outcome

```gherkin
Given an orchestrating agent observes an active child session whose host pane is missing
And automatic restoration of that session fails
When agent_runtime completes the restoration attempt
Then the failure is reported once as an owned restoration outcome rather than an unhandled task exception
And a session that still has no host pane is reported as headless
And later maintenance cycles do not repeat the same failed restoration while that headless state remains
```


#### UC-SL36: Failed headless adoption preserves an adoptable session

```gherkin
Given an agent controls a previously live session whose host pane is absent
And automatic restoration has recorded the session as headless with no pane binding
When a control action attempts headless adoption and host-pane creation fails
Then the session remains headless with no pane binding
And the failed attempt does not report the session as initializing
And a later interaction may attempt the same sanctioned headless adoption path
```


#### Ending a session — happy path

```
Given a caller with clearance to end sessions and ownership of the session
When the caller asks the agent_runtime service to end the session
Then the entry authorizes the caller as an owner
And builds a close-session command
And dispatches it through the command service
And accepts the request asynchronously, identifying the completion event consumers can subscribe to
And the actual termination work (host-pane termination, resource cleanup, lifecycle transition) is performed asynchronously by the cleanup module — see session-cleanup-and-reaping
```

#### Ending a missing or already-closed session

```
Given the supplied session id does not exist in storage
When the caller asks the agent_runtime service to end the session
Then the entry path's session state read finds no row and does not reject the request
And the close command is dispatched and the request is accepted as usual
And the inner termination reports no transition and is logged at debug
And no error is surfaced to the caller for a missing session
```

```
Given the session id exists but is already terminal (closed-at marker non-null or lifecycle status `closed`)
When the caller asks the agent_runtime service to end the session
Then the entry path reads the stored session state before dispatching
And responds that the session is already closed instead of accepting another close
And that response is a synchronous success (HTTP 200), distinct from the asynchronous acceptance (HTTP 202) of a dispatched close, and both statuses are declared on the endpoint's API contract
And no close command is dispatched
And a human-initiated close still sets the manual-close todo hold (the explicit halt applies regardless of the target's state)
```

```
Given the session id exists with lifecycle status `closing` but no closed-at marker
When the caller asks the agent_runtime service to end the session
Then the session is not treated as terminal (a stuck or in-flight close must still be able to finalize)
And the close command is dispatched and the request is accepted as usual
```

#### UC-SL37: Manual close distinguishes lifecycle-driver relationships

```gherkin
Given an agent observes a human-originated close for a session in a project
When the session is the current lifecycle driver
Then its todo is held before the close continues
When the session is a non-driver worker whose current driver is known
Or the session is a former driver whose release is recorded
Then the close continues without changing todo state
And the driver relationship is reported as an explained no-op
When no current or recorded relationship explains the session
Then the close continues without changing todo state
And the unexplained correlation is reported
```

#### UC-SL30: Caller-scoped termination closes every direct child and nothing else

```gherkin
Given an agent session has zero or more live direct child sessions, possibly on different computers
When the agent asks to end its child sessions without naming one child
Then every live session whose direct initiator is the caller is closed
And sessions outside that direct caller scope are untouched
And the operation succeeds immediately when the caller has no live direct children
And otherwise succeeds only after no live direct child remains
And a child that cannot be closed leaves the operation failed with the residual child identified
And a caller that cannot be identified is refused before any session is affected
And a targetless request with a computer override is refused before any session is affected
```

#### UC-SL38: Requested close returns a durable receipt

```gherkin
Given a caller asks to close a session
When the request is accepted
Then a durable operation row is persisted before cleanup begins and the response carries its receipt
And the receipt names the operation, its state, where to read it, the computer that owns it, and the success and failure events it will emit
And cleanup runs as that operation's work, so its terminal row and its outcome event are written together
And the caller recorded on the row is woken with the outcome and where to read it
And a caller that waits instead reads the same terminal record from the operation itself
```

#### Direct-link sessions

```
Given the caller passes `direct=true` AND has a caller session
When the new session is created
Then the direct-link initiator resolves both endpoints (titles, computer names, fallback to ids)
And the link is materialized via the standard ignition path
And the launch intent's message is wrapped with the direct-conversation protocol header and rules block
And the conversation link operates orthogonally to stop-listener subscriptions
```

### Cross-context references

- **identity** — origin resolution plus the identity resolver resolve principal binding (human_email, human_role, person identity) for the Session aggregate.
- **config** — the computer name, host-pane binary, help-desk directory, enabled agents and defaults flow in via configuration resolution.
- **session_mirrors** — downstream consumer of the session-lifecycle events emitted as the Session moves through `initializing -> active -> closed`. The lifecycle write here is the source of those events.
- **workflow** — orchestrators dispatched as child sessions via this surface receive completion notifications through the one-shot stop-listener wired during create-session.


- **integration** — the Discord-owned session-address capability constructs the address a listed session carries; this surface consumes that contract and never builds an address itself.


## Known caveats

- **Host-pane reference uses the full session id.** The format is `<teleclaude-prefix><session-id>` with the full id; the v2-target domain spec phrases it as a short id for readability, but no shortening occurs here.
- **Remote direct-link creation is not the normal path.** Remote create-session supports the TUI/CLI create-session shapes (`agent`, `agent_then_message`, `agent_resume`) and returns peer ownership via `computer=<remote>`. Direct-conversation linkage still materializes through local session records and is not created by the remote dispatch branch.
- **Host-pane creation and agent launch are off the request path.** Create-session only writes the session row and returns; host-pane creation and agent CLI launch happen on the bootstrap task after acceptance. Callers polling for host-pane readiness must subscribe to the `agent_runtime.session.started` event or poll downstream — this surface does not block until the pane is alive.
- **Host-pane ensure is silently idempotent.** A name collision joins the existing host pane without recreating — uniqueness is statistical (UUID4) rather than enforced by an explicit precheck. The v2-target "agent_runtime service refuses to start a session whose host-pane name collides" is not a v1 behavior; v1 simply joins the existing host pane if one with the same name already exists.
- **End-session answers after the fact, not in its response.** Acceptance means "accepted for processing", not "closed". The outcome of cleanup is carried by the durable operation the receipt names: the caller reads that record whenever it asks, and is woken with its address when the operation reaches a terminal state.
- **Listing reveals everything reachable.** TUI and tool clients are unfiltered. The caller-session-id header is what trims a tool-client's default view to caller-scoped — `?all=true` opts out.
- **Non-admin non-system-role sessions are jailed to the help-desk directory.** When the request has no system role and the human role is anything other than admin, the project_path is forcibly replaced with the configured help-desk directory and `subfolder` / `working_slug` are cleared. This is policy, not failure.
- **The closed-at marker is set by the cleanup module, not this surface.** This surface only enqueues; see `session-cleanup-and-reaping` for the lifecycle field transitions and `agent_runtime.session.ended` payload.

## See Also

- docs/project/spec/feature/agent_runtime/session-authority.md — which session may act on which, and why a standing session is outside every caller-scoped termination.
