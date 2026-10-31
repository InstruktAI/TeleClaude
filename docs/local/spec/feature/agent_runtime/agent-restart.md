---
description: Restart the agent process inside a live TeleClaude session by terminating
  the running agent and relaunching it with resume-from-transcript so the session
  row, hosting pane, and native transcript chain survive.
visibility: public
---

# Agent Restart — Spec

## Required reads

- @docs/local/spec/domain/agent_runtime.md

## What it is

Agent restart is the verb that swaps the agent CLI process inside an already-bound TeleClaude session without disturbing the session ledger row, the hosting pane that runs it, or the native transcript chain. A caller asks the agent_runtime service to restart the agent for a given session; the service validates that the session is restart-eligible, accepts the request, and performs the swap asynchronously. The handler terminates the agent process directly so a mid-tool-execution agent still exits, waits for the host shell to become quiescent, and relaunches the agent CLI with resume-from-transcript semantics — the agent reads its own transcript on startup and continues from where it left off.

A special `self` form is dispatched by orchestrators that want to restart themselves. The CLI verb `telec sessions restart self` resolves the caller's own session identity from the local identity record and asks the agent_runtime service to restart that session. The handler subscribes to a session-ready signal before issuing the relaunch (the agent's session start event can race the relaunch and emit readiness before any post-hoc subscriber attaches), waits for readiness, and hands the continuation stimulus to control delivery. The resumed prompt receives only the standard wake marker; submitting that marker delivers the continuation as platform control context for the fresh turn. Non-self restarts skip the stimulus — the existing transcript is allowed to dictate behavior.

A restart requires a bound agent, its recorded native session, and that agent's continued enablement; it never selects a replacement agent. A self-restart readiness timeout leaves the session alive and reports that no continuation was sent. After control delivery accepts a continuation, the payload remains pending if its wake is not accepted, so a later boundary can deliver it once. A continuation supplied after maintenance restores a missing host pane follows the same control-delivery contract and remains platform control rather than foreground composer text.

Restart-failure notices remain actionable, coalesce repeated failures for one session, and remain distinct from other notifications for that session.

## Canonical fields

### Use cases

#### UC-AR13: Restart eligibility requires a resumable native binding

#### UC-AR14: Accepted restart returns a durable receipt

```
Given a person asks to restart an eligible session without waiting for the restart to finish
When the request is accepted
Then the person receives a receipt they can use to inspect the eventual success or failure
```

#### UC-AR15: Restart waits for direct process termination before relaunch

#### UC-AR16: Restart relaunches in place with native transcript continuity

```
Given a person wants to restart an agent while keeping its existing session
When the restart succeeds
Then the same session continues from its native conversation
```

#### UC-AR1: Self-restart wakes the resumed agent without foregrounding the continuation

```gherkin
Given an agent acting for a person needs to restart its own session
When the restart succeeds
Then the same session continues its pending work with the continuation as platform control, not human input
```

#### UC-AR2: Self-restart retries only the wake submission

#### UC-AR3: Self-restart fails loud when the wake cannot start a turn

#### UC-AR4: Non-self restart skips the continuation stimulus

#### UC-AR17: Restart revives a closed session as recorded

#### UC-AR18: Restart binds a replacement pane for a missing host pane

#### UC-AR19: Restart fails when the target agent is disabled

#### UC-AR5: Restart a session owned by a remote computer

#### UC-AR20: Restart refuses a remote session when its owner is omitted

#### UC-AR6: The operator is notified when an agent restart fails

```gherkin
Scenario Outline: Restart failure reaches the operator
  Given a restart failure occurs because <cause>
  When the failure is reported
  Then the operator receives an actionable restart-failure notification
  And the in-session failure message remains visible in the session pane

  Examples:
    | cause |
    | the agent process did not exit and the shell never returned ready |
    | the target agent is no longer enabled in configuration |
    | a self-restart readiness timeout prevented continuation delivery |
```

#### UC-AR7: Disabled-agent restart abort notifies the operator

#### UC-AR8: Self-restart readiness-timeout notifies the operator

#### UC-AR9: Repeated restart failures for one session coalesce into one operator notification

#### UC-AR10: A restart-failure notification is distinct from other same-session notifications

#### UC-AR11: Self-restart relaunches only after the terminated agent process is confirmed exited

#### UC-AR12: Maintenance restoration wakes the resumed agent without foregrounding the continuation

<!-- planned:restart-relaunch-fuses-shell-line -->

#### UC-AR21: Restart relaunches cleanly over unsubmitted shell input

```
Given a person restarts an agent while text typed into its host shell has not been submitted
When the restart succeeds
Then the same session continues from its native conversation exactly as the restart launched it
And the unsubmitted text never reaches the agent
```

<!-- /planned:restart-relaunch-fuses-shell-line -->

### Cross-context references

- **identity** — clearance for agent restart is enforced at the boundary; the handler does not re-validate identity mid-flight. The `self` form resolves the caller's own session via the local identity record, which is the same source consulted for clearance.
- **session_mirrors** — restart preserves the session id, native session identifier, and transcript file chain, so the mirror layer sees an uninterrupted continuation of the same record; no mirror reseed is required, and external observers reading transcript files keep the same handle.
- **workflow** — operations bound to the session (e.g., dispatched lifecycle commands waiting on completion events) are NOT cancelled by restart; the relaunch publishes `agent_runtime.agent.restarted` so coordinators can observe the cycle without losing their existing bindings.

## Known caveats

- **Restart does not cancel in-flight subscribers.** Listeners registered against the session, direct links the session participates in, and event subscriptions (other than the self-restart readiness handler) survive the agent process swap. This is deliberate — restart targets the agent CLI, not the session's collaboration surface.
- **The kill-side barrier is the only gate between kill and launch.** The barrier requires both the terminated agent process to be confirmed exited and the host shell prompt to return, under one deadline. If it times out (the process did not exit or the prompt did not return), restart aborts; there is no escalating force-kill today.
- **Self-restart relies on pre-subscription to the readiness signal.** The handler subscribes before the relaunch because the agent's session start event can fire before any post-launch subscriber would attach. A future agent that ships its readiness event differently must keep this invariant or the continuation stimulus will be skipped via timeout.
- **Continuation stimulus is fixed text.** The constant "Session restarted. Continue pending work or remain idle." is the only stimulus the platform supplies to control delivery on self-restart; there is no caller-supplied payload.
- **`self` semantics are CLI-side only.** The agent_runtime service takes a concrete session id; the literal `self` is resolved in `telec sessions restart` by reading the local identity record, not by the service. A direct service caller must address a concrete session id.
- **Self-restart is flag-shaped on the request.** A request that fails to carry the self-restart flag is silently treated as a non-self restart.

- **Restart on a dead host pane quietly binds a new one.** If the recorded host pane no longer exists, restart does not error — it binds a fresh host pane before relaunch, so callers may observe a different host-pane reference after the cycle than the one they passed in.
