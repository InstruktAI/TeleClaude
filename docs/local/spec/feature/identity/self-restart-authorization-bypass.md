---
description: 'Allow any authenticated session to restart itself via the agent-restart action, bypassing the normal `telec sessions restart` clearance.'
visibility: 'public'
---

# Self-Restart Authorization Bypass — Spec

## Required reads

- @docs/local/spec/domain/identity.md
- @docs/local/spec/identity-and-auth.md

## What it is

The agent-restart action is the one place where v1 deliberately diverges from the verb-based clearance rule. Normally `telec sessions restart` is restricted (notably, focused-role agent sessions are excluded), but a focused session that has gone unresponsive must be able to recover itself. Command clearance for `telec sessions restart` therefore recognises a "self-restart" shape — a caller resolved to a session, restarting that same session — and admits it without consulting the verb allowlist at all. Every other shape (a cross-session restart, or a caller that is not a session) falls through to the standard rule, and a focused session is refused a cross-session restart before the generic verb check runs. The decision is made in the client process before any request is sent (`feature/identity/command-clearance`); the daemon performs the restart it receives.

## Canonical fields

### Use cases

#### UC-SRAB1: A focused session may restart its own session

#### UC-SRAB2: A focused session may not use self-restart authority on another session

#### UC-SRAB3: An orchestrator may restart another session through ordinary clearance

#### UC-SRAB4

#### UC-SRAB5

#### UC-SRAB6: A terminal caller uses ordinary human-role clearance

### Cross-context references

- This is `agent_runtime`'s session-restart flow leaning on command clearance for a single carve-out. The action handler dispatches the agent restart inside `agent_runtime` after the client has cleared it.
- The carve-out relies on the client-side caller resolution (`local/projects/teleclaude/spec/identity-and-auth` §6) having resolved the caller to its session record — terminal and TUI callers cannot self-restart anything.
- The agent-restart action also emits an `agent_runtime.agent.restarted` event on successful dispatch (see the v2 event taxonomy).
- The session authority rule the daemon applies to the restart it performs is unchanged by this carve-out: a session never restarts the orchestrator that dispatched it (`local/projects/teleclaude/spec/feature/agent_runtime/session-authority`).
- In v2 the carve-out disappears from identity. `agent_runtime` defines its own "may restart self" authorization rule and evaluates it against the resolved `Principal`. Identity returns the Principal only; the cross-cutting verb table no longer needs a special case.

## Known caveats

- The carve-out applies ONLY when the caller resolves to a session and the target is exactly that session. Terminal and TUI callers (no session) and callers acting on a different session go through the standard rule.
- The focused-role short-circuit is intentional defence-in-depth. Even if a future change added `focused` to the system band for `telec sessions restart`, the explicit focused-role check still refuses a cross-session restart by a focused session. The only path open to it is the self-restart carve-out.
