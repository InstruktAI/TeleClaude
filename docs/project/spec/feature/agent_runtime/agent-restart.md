---
id: 'project/spec/feature/agent_runtime/agent-restart'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Restart the agent process inside a live TeleClaude session by terminating the running agent and relaunching it with --resume so the session row, tmux pane, and native transcript chain survive.'
---

# Agent Restart — Spec

## Required reads

- @docs/project/spec/domain/agent_runtime.md

## What it is

Agent restart is the verb that swaps the agent CLI process inside an already-bound TeleClaude session without disturbing the session ledger row, the tmux session that hosts it, or the native transcript chain. The HTTP entry point `POST /sessions/{session_id}/agent-restart` validates the session is restart-eligible, returns 202 immediately, and dispatches `restart_agent` as a background asyncio task. The handler sends SIGTERM directly to the agent's PID (bypassing tmux's keystroke layer so a mid-tool-execution agent still exits), waits for the shell prompt to return, and relaunches the agent CLI with `--resume <native_session_id>` — the agent reads its own transcript on startup and continues from where it left off.

A special `self` form is dispatched by orchestrators that want to restart themselves. The CLI verb `telec sessions restart self` resolves the caller's own session id from `$TMPDIR/teleclaude_identity.json` and sends `{self_restart: true}` in the body. The handler subscribes to `AGENT_READY` before issuing the relaunch (the agent's `SessionStart` hook can race the relaunch and emit readiness before any post-hoc subscriber attaches), waits for readiness, and injects a continuation stimulus message so the resumed agent has a fresh user turn to act on. Non-self restarts skip the stimulus — the existing transcript is allowed to dictate behavior.

## Canonical fields

### Behavioral contract

#### Eligibility gates (HTTP boundary)

```
Given a caller POSTs /sessions/<session_id>/agent-restart with a valid bearer
When the API loads the session row
Then if the row does not exist, the daemon returns HTTP 404 "Session not found"
And if active_agent is unset, the daemon returns HTTP 409 "No active agent for this session"
And if native_session_id is unset, the daemon returns HTTP 409 "No native session ID - start agent first"
```

```
Given the eligibility gates pass
When the API has accepted the request
Then the daemon dispatches restart_agent via asyncio.create_task (no await)
And the HTTP response is 202 with body `{status: "accepted", completion_event: "agent.restart_dispatched"}`
And no readiness information is encoded in the HTTP response
```

#### Process replacement (kill side)

```
Given restart_agent has been dispatched
When the handler stops the running agent
Then it resolves the tmux pane PID, finds its first child PID, and sends SIGTERM directly to that PID
And it does NOT send Ctrl-C through `tmux send-keys` (that path is swallowed when the agent is mid-tool-execution)
And it waits for the tmux shell to be ready (prompt returned) before relaunching
And if the shell does not become ready, the handler aborts with "Agent did not exit after SIGINT. Restart aborted."
And the abort is emitted as an ERROR event and an in-session message
```

#### Process replacement (launch side)

```
Given the agent process has exited and the shell is ready
When the handler relaunches the agent
Then it constructs the agent command via get_agent_command with `--resume <native_session_id>` and the session's thinking_mode (defaulting to "slow")
And it sends the command into the existing tmux session via execute_terminal_command
And the tmux_session_name, session_id, native_session_id, and transcript chain are preserved
And the agent CLI replays its own transcript on startup so the resumed agent observes its prior context
And the handler emits `agent.restart_dispatched` (AgentRestartDispatchedPayload) on the event bus, CLUSTER visibility
```

#### Self-restart and the continuation stimulus

```
Given the request body carries `{self_restart: true}`
When the handler enters the relaunch phase
Then it subscribes to AGENT_READY BEFORE issuing the relaunch (the SessionStart hook can fire before a post-hoc subscriber would attach)
And after the relaunch, it awaits AGENT_READY for the session (with a bounded timeout AGENT_PROMPT_READY_TIMEOUT_S)
And on readiness, it sends the constant `RESTART_CONTINUATION_STIMULUS` ("Session restarted. Continue pending work or remain idle.") into the tmux pane as a user-turn message
And on readiness timeout, it emits AGENT_READINESS_TIMEOUT and posts a message to the user but does NOT inject the stimulus
And the AGENT_READY subscription is unsubscribed in a finally block
```

```
Given the request body does NOT set `self_restart`
When the handler enters the relaunch phase
Then the relaunch is issued without subscribing to AGENT_READY
And no continuation stimulus is injected
And the resumed agent acts on whatever its replayed transcript dictates
```

#### Closed / detached / headless recovery

```
Given the target session row has closed_at set
When restart_agent runs
Then it clears closed_at, sets lifecycle_status = "headless", and re-reads the row before continuing
And revival of a closed session is a side effect of restart, not a separate code path
```

```
Given the row's tmux_session_name no longer exists on the host
When restart_agent runs
Then it clears tmux_session_name, sets lifecycle_status = "headless", and re-reads the row
And it adopts a fresh tmux session via _ensure_tmux_for_headless before relaunch
And if adoption fails, restart returns (False, "Failed to adopt headless session.")
```

#### Agent-enablement check

```
Given the target_agent (active_agent of the session) is no longer enabled in config
When restart_agent calls assert_agent_enabled(target_agent)
Then it raises ValueError, restart_agent aborts with that message
And an ERROR event is emitted (source = "agent_restart") and a "❌" message is sent to the session
```

### Implementation pointers (v1)

- HTTP route: `teleclaude/api/sessions_actions_routes.py:457` (`agent_restart`)
- Command handler: `teleclaude/core/command_handlers/_agent.py:311` (`agent_restart`)
- Direct PID SIGTERM: `teleclaude/core/command_handlers/_agent.py:276` (`_terminate_agent_process`)
- Continuation stimulus constant: `teleclaude/constants.py:247` (`RESTART_CONTINUATION_STIMULUS`)
- Command type: `teleclaude/types/commands.py:361` (`RestartAgentCommand` with `self_restart: bool`)
- Command-service entry: `teleclaude/core/command_service.py` (`restart_agent` → calls `agent_restart`)
- CLI verb: `teleclaude/cli/tool_commands/sessions.py:459` (`handle_sessions_restart`), with `self` resolved from `$TMPDIR/teleclaude_identity.json` via `get_session_id()`
- Self-restart body wiring: `teleclaude/cli/tool_commands/sessions.py:492` (sends `{self_restart: true}` only when CLI arg is the literal `self`)
- Clearance dependency: `clearance_sessions_agent_restart` in `teleclaude/api/auth.py`

### Cross-context references

- **identity** — `clearance_sessions_agent_restart` enforces the bearer token and role on the HTTP boundary; the handler does not re-validate identity mid-flight after the dependency succeeds. The `self` form resolves the caller's own session via `$TMPDIR/teleclaude_identity.json`, which is the same identity file `clearance_sessions_*` consults.
- **session_mirrors** — restart preserves `session_id`, `native_session_id`, and the transcript file chain, so the mirror layer sees an uninterrupted continuation of the same record; no mirror reseed is required, and external observers reading transcript files keep the same handle.
- **workflow** — operations bound to the session (e.g., dispatched `next-*` commands waiting on completion events) are NOT cancelled by restart; the relaunch publishes `agent.restart_dispatched` so coordinators can observe the cycle without losing their existing bindings.

## Known caveats

- **Restart does not cancel in-flight subscribers.** Listener rows registered against the session_id, direct-links the session participates in, and event-bus subscriptions (other than the self-restart `AGENT_READY` handler) survive the agent process swap. This is deliberate — restart targets the agent CLI, not the session's collaboration surface.
- **The shell-ready wait is the only barrier between kill and launch.** If `wait_for_shell_ready` returns false (SIGTERM didn't take, prompt didn't return), restart aborts; there is no escalating SIGKILL today.
- **Self-restart relies on event-bus pre-subscription.** The handler subscribes to `AGENT_READY` BEFORE the relaunch because the agent's `SessionStart` hook can fire before any post-launch subscriber would attach. A future agent that ships its readiness event differently must keep this invariant or the continuation stimulus will be skipped via timeout.
- **Continuation stimulus is fixed text.** The constant `"Session restarted. Continue pending work or remain idle."` is the only stimulus the handler injects on self-restart; there is no caller-supplied payload.
- **`self` semantics are CLI-side only.** The HTTP endpoint takes a concrete session id in the path; the literal `self` is resolved in `telec sessions restart` by reading the local identity file, not by the daemon. A direct HTTP caller must POST to a concrete `session_id`.
- **`self_restart` is body-shaped, not query-shaped.** The flag travels in the JSON body of the POST and is only read when the request's `Content-Type` is `application/json`. A `self_restart: true` body sent with the wrong content type is silently treated as a non-self restart.
- **Restart on a dead tmux quietly switches to adoption.** If the recorded `tmux_session_name` no longer exists, restart does not error — it adopts a fresh tmux session in headless mode before relaunch, so callers may observe a different `tmux_session_name` after the cycle than the one they passed in.
