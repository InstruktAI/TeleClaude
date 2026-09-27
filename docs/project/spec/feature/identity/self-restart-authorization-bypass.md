---
description: 'Allow any authenticated session to restart itself via the agent-restart action, bypassing the normal `telec sessions restart` clearance.'
visibility: 'public'
---

# Self-Restart Authorization Bypass — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The agent-restart action is the one place where v1 deliberately diverges from the verb-based clearance rule. Normally `telec sessions restart` is restricted (notably, worker-Role agent sessions are excluded), but a worker that has gone unresponsive must be able to recover itself. Command clearance for `telec sessions restart` therefore recognises a "self-restart" shape — a caller resolved to a session, restarting that same session — and admits it without consulting the verb allowlist at all. Every other shape (a cross-session restart, or a caller that is not a session) falls through to the standard rule, and a worker is refused a cross-session restart before the generic verb check runs. The decision is made in the client process before any request is sent (`feature/identity/command-clearance`); the daemon performs the restart it receives.

## Canonical fields

### Use cases

#### UC-SRAB1: A worker may restart its own session

```gherkin
Given a worker agent session with system_role=`worker`
When the session restarts its own agent
Then clearance admits the self-restart (the target is the caller's own session)
And the standard verb allowlist is not consulted
And the restart is dispatched
```

#### UC-SRAB2: A worker may not use self-restart authority on another session

```gherkin
Given the same worker session
When it restarts the agent of a DIFFERENT session
Then the self-restart shape does not apply (the target is another session)
And the worker short-circuit refuses the restart
And the refusal is the not-permitted failure for `telec sessions restart`, given before any request is sent
```

#### UC-SRAB3: An orchestrator may restart another session through ordinary clearance

```gherkin
Given an orchestrator-Role agent session (system_role=`orchestrator`) whose Role is in the `telec sessions restart` system band
When it restarts the agent of another session
Then the self-restart shape does not apply
And the standard verb clearance admits the orchestrator
And the cross-session restart is dispatched
```

#### UC-SRAB4

#### UC-SRAB5

#### UC-SRAB6: A terminal caller uses ordinary human-role clearance

```gherkin
Given an operator at a terminal or in the TUI, outside any session
When they restart a session's agent
Then the self-restart shape does not apply (the caller is not a session)
And the standard rule runs against the person's role
And admin callers restart the agent; others are refused before any request is sent
```

### Cross-context references

- This is `agent_runtime`'s session-restart flow leaning on command clearance for a single carve-out. The action handler dispatches the agent restart inside `agent_runtime` after the client has cleared it.
- The carve-out relies on the client-side caller resolution (`project/spec/identity-and-auth` §6) having resolved the caller to its session record — terminal and TUI callers cannot self-restart anything.
- The agent-restart action also emits an `agent_runtime.agent.restarted` event on successful dispatch (see the v2 event taxonomy).
- The session authority rule the daemon applies to the restart it performs is unchanged by this carve-out: a session never restarts a session above it (`project/spec/feature/agent_runtime/session-authority`).
- In v2 the carve-out disappears from identity. `agent_runtime` defines its own "may restart self" authorization rule and evaluates it against the resolved `Principal`. Identity returns the Principal only; the cross-cutting verb table no longer needs a special case.

## Known caveats

- The carve-out applies ONLY when the caller resolves to a session and the target is exactly that session. Terminal and TUI callers (no session) and callers acting on a different session go through the standard rule.
- The worker short-circuit is intentional defence-in-depth. Even if a future change added `worker` to the system band for `telec sessions restart`, the explicit worker check still refuses a cross-session restart by a worker. The only path open to it is the self-restart carve-out.
