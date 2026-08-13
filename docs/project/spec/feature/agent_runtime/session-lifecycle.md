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
And the request carries an `origin` (terminal or web) and an enabled `agent`
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
Given the request supplies origin metadata (web or terminal email payload)
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
Then the session record's human_role is admin, resolved by the auth layer (verify_caller), not by a model default
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

```
Given the caller passes a message in the create request
And the launch kind is `agent` (the default)
When the launch-intent builder runs
Then the launch kind is upgraded to `agent_then_message`
And the launch intent is built with agent, thinking mode, and message
And the message is persisted on the launch intent
And once the agent CLI is ready, the bootstrap task submits the message through prompt-state startup delivery
And prompt-state startup delivery captures the live prompt input state before paste
And prompt-state startup delivery attempts the paste exactly once
And after paste, it waits until the live prompt input changes from its pre-paste state to effective user input before sending Enter
And effective user input is any real prompt occupancy, including collapsed paste markers beginning with `[Pasted `
And generated or styled suggestion text in the prompt counts as empty input
And prompt-state startup delivery sends Enter as soon as changed effective user input is observed
And when a post-Enter observation shows the live prompt input is no longer effectively occupied, or a submitted/agent-active pane boundary is visible, the launch result is success and output polling starts
And if `user_prompt_submit` arrives while prompt-state startup delivery is still observing or retrying, it also stops delivery as success but is not required for success
And if effective user input is never observed after the single paste attempt, the launch result is an error rather than a re-paste
And the initiator extraction records the caller's session id so the spawned child can notify the initiator on stop (one-shot listener)
```

#### UC-SL25: Startup message enter retries do not re-paste

```
Given the caller passes a message in the create request
And the live prompt input contains changed effective user input after the single paste
When Enter is sent but the post-Enter pane observation still shows effective user input in the live prompt
Then prompt-state startup delivery re-captures and re-classifies the live prompt before each retry
And while effective user input remains in the live prompt, it retries Enter without clearing or re-pasting the message
And if the live prompt input becomes empty, generated-only, or replaced by a submitted/agent-active pane boundary, it stops retrying and reports success
And if effective user input remains in the live prompt after the retry budget, the launch result is an error rather than a silent success
```

#### UC-SL26: Historical prompt text does not confirm startup delivery

```
Given the caller passes a message in the create request
And the pane output contains that message only in historical scrollback
When prompt-state startup delivery observes the pane
Then the historical copy does not satisfy the live prompt input check
And an unchanged pre-existing live prompt input does not satisfy the live prompt input check
And generated or styled suggestion text in the live prompt does not satisfy the live prompt input check
And Enter is not sent from that observation
And the launch result is an error rather than a silent success
```

#### Initiator listener registration

```
Given the caller's session is non-web (initiator session id present and not `web:`-prefixed)
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
And role-based filtering is then applied (see below)
And optional `job` filter narrows further
And the human display name is enriched from the people configuration for each entry whose email matches
```

#### Listing sessions — role-based visibility

```
Given the web client sends identity headers for email and role
When the role-based filter applies
Then role `admin` sees every session
And role `member` sees their own sessions PLUS sessions with visibility "shared"
And role `contributor` / `newcomer` / unknown sees only their own sessions (matched by human_email)
And requests without identity headers (TUI / tool clients) are NOT filtered by role — they see everything reachable
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

#### UC-SL23: An activity hook activates an initializing session

```
Given a non-headless session row exists with `lifecycle_status="initializing"`
And the agent CLI process emits any activity hook for it (session_start, agent_stop, tool_use, or user_prompt_submit)
When agent_runtime handles the hook
Then the session row is updated with `lifecycle_status="active"`
And `native_session_id` and `native_log_file` are stored when the session_start hook carries them
And normal live-session listing returns the session without requiring `include_initializing`
And headless or closed lifecycle rows are not reactivated by any activity hook
```

<!-- planned:session-bootstrap-strands-initializing -->

#### UC-SL27: Bootstrap failure resolves the session terminally

```
Given a non-headless session row exists with `lifecycle_status="initializing"`
And its bootstrap cannot complete — host-pane creation fails, the bootstrap raises, or the bootstrap task is never scheduled
When the bootstrap outcome is resolved
Then the session does not remain `initializing`
And the session is recorded as terminally closed
And a session bootstrap-failure event is published for that session
And a caller delivering input to that session is refused rather than left waiting on the startup gate
```

<!-- /planned:session-bootstrap-strands-initializing -->

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
When the close command runs
Then the inner termination reports no transition and is logged at debug
And the entry path still accepts the request (the entry does not pre-check existence)
And no error is surfaced to the caller for a missing session
```

```
Given the session id exists but is already marked closed (closed-at marker non-null)
When the close command runs
Then the cleanup module proceeds with resource cleanup for any straggling artifacts (channel delete, workspace removal, tmpdir delete) but skips the closing -> closed lifecycle write
And the entry path accepts the request as usual
```

#### Direct-link sessions

```
Given the caller passes `direct=true` AND has a non-web caller session
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

## Known caveats

- **Host-pane reference uses the full session id.** The format is `<teleclaude-prefix><session-id>` with the full id; the v2-target domain spec phrases it as a short id for readability, but no shortening occurs here.
- **Remote direct-link creation is not the normal path.** Remote create-session supports the TUI/CLI create-session shapes (`agent`, `agent_then_message`, `agent_resume`) and returns peer ownership via `computer=<remote>`. Direct-conversation linkage still materializes through local session records and is not created by the remote dispatch branch.
- **Host-pane creation and agent launch are off the request path.** Create-session only writes the session row and returns; host-pane creation and agent CLI launch happen on the bootstrap task after acceptance. Callers polling for host-pane readiness must subscribe to the `agent_runtime.session.started` event or poll downstream — this surface does not block until the pane is alive.
- **Host-pane ensure is silently idempotent.** A name collision joins the existing host pane without recreating — uniqueness is statistical (UUID4) rather than enforced by an explicit precheck. The v2-target "agent_runtime service refuses to start a session whose host-pane name collides" is not a v1 behavior; v1 simply joins the existing host pane if one with the same name already exists.
- **End-session is fire-and-forget.** Acceptance means "accepted for processing", not "closed". The caller does not learn the outcome of cleanup over this surface; subscribing to the completion event (named in the acceptance response) or listing closed sessions is required.
- **Listing without identity headers reveals everything.** TUI and tool clients are intentionally unfiltered. Role-based gating is only applied when the web identity headers are present. The caller-session-id header is what trims a tool-client's default view to caller-scoped — `?all=true` opts out.
- **Non-admin non-system-role sessions are jailed to the help-desk directory.** When the request has no system role and the human role is anything other than admin, the project_path is forcibly replaced with the configured help-desk directory and `subfolder` / `working_slug` are cleared. This is policy, not failure.
- **The closed-at marker is set by the cleanup module, not this surface.** This surface only enqueues; see `session-cleanup-and-reaping` for the lifecycle field transitions and `agent_runtime.session.ended` payload.
