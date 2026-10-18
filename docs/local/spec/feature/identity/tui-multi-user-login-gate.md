---
description: 'Block TUI startup until `telec auth login` has been run when the global config lists more than one person; single-user configurations bypass the gate.'
visibility: 'public'
---

# TUI Multi-User Login Gate — Spec

## Required reads

- @docs/local/spec/domain/identity.md
- @docs/local/spec/identity-and-auth.md

## What it is

The startup-time check that prevents an anonymous operator from launching the trusted TUI on a host configured for multiple people. When `telec` is invoked with no arguments — the canonical "open the TUI" entry point — the launcher inspects the configured `people` list. If the list contains more than one person, the launcher refuses to start the TUI until the operator has run `telec auth login <email>` on the current TTY. Single-user configurations (zero or one person) skip the gate entirely, preserving the convenience of solo-operator setups. When the gate passes, the launcher spawns a fresh `tc_tui` tmux session marked with the TUI runtime marker; that marker is what later authorizes the identity context to trust an in-tmux terminal-email signal for the duration of the TUI's lifetime.

An invocation already inside the marked TUI session dispatches in-process without re-evaluating the gate or creating a nested TUI session.

## Canonical fields

### Use cases

#### UC-TUIG1: An operator opens the TUI under the identity of their terminal

```gherkin
Scenario: A multi-user terminal opens the TUI as its selected person
  Given more than one person is registered
  And the operator has signed in on the current terminal
  When they open the TUI
  Then protected TUI actions use the selected person's identity

Scenario: A multi-user terminal without a login is told how to sign in
  Given more than one person is registered
  And the current terminal has no saved login
  When the operator opens the TUI
  Then the TUI does not start
  And the operator is told to run `telec auth login <email>`
  And the command exits with failure
  And no TUI session is created

Scenario: A solo terminal opens without another login step
  Given zero or one person is registered
  And the current terminal has no saved login
  When the operator opens the TUI
  Then the TUI starts without requiring a login
```

#### UC-TUIG2: The TUI presents the identity it was launched with, not its own pane's

#### UC-TUIG3: The carried identity is honoured only where the TUI runtime marker is present

#### UC-TUIG4: The marker reaches the TUI session and no other

### Cross-context references

- Reads `config.people` to count registered persons; the count is the sole gate criterion.
- Producer of the trusted-TUI marker (the TUI runtime marker inside tmux session `tc_tui`) consumed by the client-side caller resolution (`local/projects/teleclaude/spec/identity-and-auth` §6) — the TUI's launched identity is honoured only where the marker is present.
- Coordinates with `agent_runtime` insofar as the TUI runs inside a tmux session the launcher creates; the `tc_tui` session is distinct from agent-session tmux names (`tc_<session_id_short>`) and is not part of the managed session table.
- Depends on `feature/identity/terminal-email-login` as its prerequisite: the gate is satisfied only when that flow has previously written a live auth document for the current TTY.
- No v1 domain event is emitted by the gate. The behavior is local launcher policy, not an identity-context state change.

## Known caveats

- The gate is a one-shot startup check. Adding or removing people from the config while the TUI is already running does not retroactively kick the operator out — the next TUI launch re-evaluates.
- A reachable but unparseable global config makes the gate predicate return False (fail-open). The fail-open posture preserves usability on a half-configured host but means a corrupted multi-user config silently degrades the gate to no-op. Operators relying on this gate as a security control should monitor `config validate`.
- The gate trusts that any prior login document on the current TTY belongs to an authorized operator. The launcher does not re-validate the email against the live `people` list before opening the TUI — the identity context does that lookup later on the first protected call. A stale auth document whose email was removed from `people` will pass the gate but fail on the first protected call.
- The launcher kills any existing `tc_tui` tmux session before spawning a new one. This is intentional (only one trusted TUI per host at a time) but means a concurrent invocation will displace an in-progress operator session without warning.
- Environment forwarding into the new tmux session is fail-closed. Only platform-owned TUI runtime keys are propagated; arbitrary shell variables and secrets are never forwarded by configuration.
