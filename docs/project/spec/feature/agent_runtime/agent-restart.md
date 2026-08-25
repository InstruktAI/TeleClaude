---
description: Restart the agent process inside a live TeleClaude session by terminating
  the running agent and relaunching it with resume-from-transcript so the session
  row, hosting pane, and native transcript chain survive.
visibility: public
---

# Agent Restart — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

Agent restart is the verb that swaps the agent CLI process inside an already-bound TeleClaude session without disturbing the session ledger row, the hosting pane that runs it, or the native transcript chain. A caller asks the agent_runtime service to restart the agent for a given session; the service validates that the session is restart-eligible, accepts the request, and performs the swap asynchronously. The handler terminates the agent process directly so a mid-tool-execution agent still exits, waits for the host shell to become quiescent, and relaunches the agent CLI with resume-from-transcript semantics — the agent reads its own transcript on startup and continues from where it left off.

A special `self` form is dispatched by orchestrators that want to restart themselves. The CLI verb `telec sessions restart self` resolves the caller's own session identity from the local identity record and asks the agent_runtime service to restart that session. The handler subscribes to a session-ready signal before issuing the relaunch (the agent's session start event can race the relaunch and emit readiness before any post-hoc subscriber attaches), waits for readiness, and injects a continuation stimulus message so the resumed agent has a fresh user turn to act on. Non-self restarts skip the stimulus — the existing transcript is allowed to dictate behavior.

## Canonical fields

### Use cases

#### Eligibility gates

```
Given a caller asks the agent_runtime service to restart the agent for a session
When the service loads the session row
Then if the row does not exist, the request is refused with a "session not found" error
And if no active agent is bound to the session, the request is refused with a "no active agent for this session" error
And if no native session identifier has been recorded, the request is refused with a "no native session ID — start agent first" error
```

```
Given the eligibility gates pass
When the service accepts the request
Then the service dispatches the restart asynchronously and returns immediately
And the response carries an acceptance signal and the name of the completion event consumers can subscribe to
And no readiness information is encoded in the acceptance response
```

#### Process replacement (kill side)

```
Given the restart has been dispatched
When the handler stops the running agent
Then it resolves the host pane's child process and sends a termination signal directly to that process
And it does NOT route the termination through pane keystrokes (that path is swallowed when the agent is mid-tool-execution)
And it waits for the host shell prompt to return before relaunching
And if the shell does not become ready, the handler aborts with "Agent did not exit after termination. Restart aborted."
And the abort is emitted as an error event and as an in-session message
```

#### Process replacement (launch side)

```
Given the agent process has exited and the shell is ready
When the handler relaunches the agent
Then it constructs the agent command with resume-from-transcript semantics and the session's recorded thinking mode (defaulting to "slow")
And it sends the command into the existing host pane
And the host pane, session_id, native session identifier, and transcript chain are preserved
And the agent CLI replays its own transcript on startup so the resumed agent observes its prior context
And the handler emits the `agent_runtime.agent.restarted` event with CLUSTER visibility
```

#### UC-AR1 (r2): Self-restart submits the continuation stimulus through prompt-state delivery

```gherkin
Given the request carries the self-restart flag
When the handler enters the relaunch phase
Then it subscribes to the session-ready signal BEFORE issuing the relaunch (the agent's session start event can fire before a post-hoc subscriber would attach)
And after the relaunch, it awaits readiness for the session within a bounded timeout, releasing the subscription in a finalizer
And on readiness, it composes the fixed continuation body ("Session restarted. Continue pending work or remain idle.") as the paired restart-continuation control envelope, whose label is distinct from the input-request label
And it submits that envelope to accepted-text delivery with the restart operation as its stable source occurrence
And the accepted row records the platform-control kind before any pane delivery begins
And the inbound worker waits for prompt readiness and captures the live prompt input state before paste
And the inbound worker pastes the stimulus exactly once
And after paste, it sends Enter as soon as the live prompt input changes from its pre-paste state to effective user input
And when a post-Enter observation shows the live prompt input is no longer effectively occupied, or a submitted/agent-active pane boundary is visible, the accepted occurrence is reported as delivered
And if `user_prompt_submit` arrives while prompt-state delivery is still observing or retrying, it also stops delivery as success but is not required for success
And on readiness timeout, the handler emits a readiness-timeout event and posts a message to the user but does NOT submit the continuation envelope
```

#### UC-AR2: Self-restart retries submit only while the stimulus remains live

```gherkin
Given the inbound worker has pasted the continuation stimulus from one accepted platform-control occurrence
And pane observation confirms changed effective user input in the live prompt input
And after submit Enter the live prompt remains effectively occupied
When prompt-state delivery retries submission
Then the inbound worker re-captures and re-classifies the pane before each retry
And while effective user input remains present in the live prompt input, it sends another Enter without clearing or re-pasting the stimulus
And if the live prompt input becomes empty, generated-only, or replaced by a submitted/agent-active pane boundary, it stops sending Enter and reports success
And the accepted occurrence is pasted exactly once with no duplicate acceptance or stimulus
```

#### UC-AR3: Self-restart fails loud on retry exhaustion

```
Given a self-restart's continuation stimulus never produces changed effective user input in the live prompt input
Or effective user input remains in the live prompt input after every bounded submit retry
When the relevant retry budget is exhausted
Then the handler reports failure and keeps the session alive, never silently dropping the stimulus
```

#### UC-AR4: Non-self restart skips the continuation stimulus

```
Given the request does NOT set the self-restart flag
When the handler enters the relaunch phase
Then the relaunch is issued without subscribing to the readiness signal
And no continuation stimulus is injected
And the resumed agent acts on whatever its replayed transcript dictates
```

#### Closed / detached / headless recovery

```
Given the target session row is marked closed
When the restart runs
Then it clears the closed marker, sets the lifecycle status to "headless", and re-reads the row before continuing
And revival of a closed session is a side effect of restart, not a separate code path
```

```
Given the row's recorded host pane no longer exists
When the restart runs
Then it clears the recorded host pane reference, sets the lifecycle status to "headless", and re-reads the row
And it adopts a fresh host pane in headless mode before relaunch
And if adoption fails, the restart reports "Failed to adopt headless session."
```

#### Agent-enablement check

```
Given the target agent is no longer enabled in configuration
When the restart consults the enablement gate
Then it aborts with that gate's error message
And an error event is emitted (sourced from agent restart) and a failure-marker message is sent to the session
```

#### UC-AR5: Restart a session owned by a remote computer

```
Given a session is owned by a remote computer
When a caller asks to restart its agent and names the owning computer
Then the restart is dispatched to the owning computer and runs against that computer's ledger
And the agent process is replaced on the owning computer exactly as for a local restart
And the acceptance response and the agent_runtime.agent.restarted completion event are the same the caller would receive for a local restart
And no restart is attempted against the local computer, which does not own the session
```

```
Given a caller asks to restart a session but names no owning computer for a session this computer does not own
When the restart request is resolved
Then the request is refused with a "session not found" error rather than silently executing locally
```

#### UC-AR6: Kill-side restart abort notifies the operator

```
Given a restart aborts because the agent process did not exit and the shell never returned ready
When the handler reports the failure
Then the operator receives an actionable restart-failure notification
And the in-session failure message remains visible in the session pane
```

#### UC-AR7: Disabled-agent restart abort notifies the operator

```
Given a restart aborts because the target agent is no longer enabled in configuration
When the handler reports the failure
Then the operator receives an actionable restart-failure notification
And the in-session failure message remains visible in the session pane
```

#### UC-AR8: Self-restart readiness-timeout notifies the operator

```
Given a self-restart relaunched the agent but readiness timed out before the continuation stimulus could be delivered
When the handler reports the timeout
Then the operator receives an actionable restart-failure notification
And the in-session timeout message remains visible in the session pane
```

#### UC-AR9: Repeated restart failures for one session coalesce into one operator notification

```
Given several restart failures occur for the same session within the platform's trailing delivery window
When the failures are reported
Then the operator receives a single external notification for that session after the window elapses
And each failure still updates the durable notification record immediately
```

#### UC-AR10: A restart-failure notification is distinct from other same-session notifications

```
Given a notification already exists for a session under that session's lifecycle grouping
When a restart failure occurs for the same session
Then the restart failure produces its own operator notification
And it does not update or resolve the pre-existing session notification
```

#### UC-AR11: Self-restart relaunches only after the terminated agent process is confirmed exited

```
Given a self-restart has sent the termination signal to the running agent process
And the host pane's foreground command reports the shell while that terminated process has not yet exited
When the handler evaluates the kill-side barrier before relaunching
Then it treats the agent as still running until the terminated process is confirmed exited, not merely because the foreground command reports the shell
And it does not relaunch the agent nor inject the continuation stimulus while the terminated process remains alive
And once the terminated process is confirmed exited it relaunches and proceeds to continuation-stimulus delivery
```

### Cross-context references

- **identity** — clearance for agent restart is enforced at the boundary; the handler does not re-validate identity mid-flight. The `self` form resolves the caller's own session via the local identity record, which is the same source consulted for clearance.
- **session_mirrors** — restart preserves the session id, native session identifier, and transcript file chain, so the mirror layer sees an uninterrupted continuation of the same record; no mirror reseed is required, and external observers reading transcript files keep the same handle.
- **workflow** — operations bound to the session (e.g., dispatched lifecycle commands waiting on completion events) are NOT cancelled by restart; the relaunch publishes `agent_runtime.agent.restarted` so coordinators can observe the cycle without losing their existing bindings.

## Known caveats

- **Restart does not cancel in-flight subscribers.** Listeners registered against the session, direct links the session participates in, and event subscriptions (other than the self-restart readiness handler) survive the agent process swap. This is deliberate — restart targets the agent CLI, not the session's collaboration surface.
- **The kill-side barrier is the only gate between kill and launch.** The barrier requires both the terminated agent process to be confirmed exited and the host shell prompt to return, under one deadline. If it times out (the process did not exit or the prompt did not return), restart aborts; there is no escalating force-kill today.
- **Self-restart relies on pre-subscription to the readiness signal.** The handler subscribes before the relaunch because the agent's session start event can fire before any post-launch subscriber would attach. A future agent that ships its readiness event differently must keep this invariant or the continuation stimulus will be skipped via timeout.
- **Continuation stimulus is fixed text.** The constant "Session restarted. Continue pending work or remain idle." is the only stimulus the handler injects on self-restart; there is no caller-supplied payload.
- **`self` semantics are CLI-side only.** The agent_runtime service takes a concrete session id; the literal `self` is resolved in `telec sessions restart` by reading the local identity record, not by the service. A direct service caller must address a concrete session id.
- **Self-restart is flag-shaped on the request.** A request that fails to carry the self-restart flag is silently treated as a non-self restart.
- **Restart on a dead host pane quietly switches to adoption.** If the recorded host pane no longer exists, restart does not error — it adopts a fresh host pane in headless mode before relaunch, so callers may observe a different host-pane reference after the cycle than the one they passed in.
