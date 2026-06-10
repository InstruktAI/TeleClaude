---
description: 'Block TUI startup until `telec auth login` has been run when the global config lists more than one person; single-user configurations bypass the gate.'
visibility: 'public'
---

# TUI Multi-User Login Gate — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The startup-time check that prevents an anonymous operator from launching the trusted TUI on a host configured for multiple people. When `telec` is invoked with no arguments — the canonical "open the TUI" entry point — the launcher inspects the configured `people` list. If the list contains more than one person, the launcher refuses to start the TUI until the operator has run `telec auth login <email>` on the current TTY. Single-user configurations (zero or one person) skip the gate entirely, preserving the convenience of solo-operator setups. When the gate passes, the launcher spawns a fresh `tc_tui` tmux session marked with the TUI runtime marker; that marker is what later authorizes the identity context to trust an in-tmux terminal-email signal for the duration of the TUI's lifetime.

## Canonical fields

### Use cases

```
Given the global config's `people` list contains two or more entries
And no `telec auth login` has been run on the current TTY (no per-TTY or global identity document)
When the operator runs `telec` (no arguments)
Then the launcher's multi-user gate predicate returns True
And the launcher prints
   "Error: telec auth login is required before starting the TUI in multi-user mode."
   "Run: telec auth login <email>"
And the process exits with a failure status
And no tmux session is created
```

```
Given the same multi-user configuration
And `telec auth login alice@example.com` has been completed on the current TTY
When the operator runs `telec`
Then the session-auth reader returns the bound email
And the launcher kills any existing tc_tui tmux session
And spawns a fresh tmux session named "tc_tui" with the TUI runtime marker
And only the platform-owned TUI environment allowlist is forwarded into the tmux session; the TUI runtime marker is set explicitly by the launcher
And `telec` is exec'd inside that tmux session
```

```
Given a global config with zero or one person registered
When the operator runs `telec` with no prior login
Then the multi-user gate predicate returns False
And the launcher proceeds without requiring login
And the TUI starts in the same tc_tui tmux session
```

```
Given any failure to load the global config (missing file, parse error)
When the multi-user gate predicate catches the load error
Then it returns False (fail-open for the gate, single-user assumption)
And the TUI launch proceeds
```

```
Given the launcher is already running inside a tmux pane that carries the TUI runtime marker
When the in-tmux TUI dispatch is reached
Then the multi-user check is NOT re-evaluated
And the in-process TUI loop runs directly (no nested tmux session is spawned)
```

### Cross-context references

- Reads `config.people` to count registered persons; the count is the sole gate criterion.
- Producer of the trusted-TUI marker (the TUI runtime marker inside tmux session `tc_tui`) consumed by `feature/identity/caller-verification` — the identity context trusts an in-tmux terminal-email signal only when both factors agree.
- Coordinates with `agent_runtime` insofar as the TUI runs inside a tmux session the launcher creates; the `tc_tui` session is distinct from agent-session tmux names (`tc_<session_id_short>`) and is not part of the managed session table.
- Depends on `feature/identity/terminal-email-login` as its prerequisite: the gate is satisfied only when that flow has previously written an auth document readable from the current TTY (or the global fallback).
- No v1 domain event is emitted by the gate. The behavior is local launcher policy, not an identity-context state change.

## Known caveats

- The gate is a one-shot startup check. Adding or removing people from the config while the TUI is already running does not retroactively kick the operator out — the next TUI launch re-evaluates.
- A reachable but unparseable global config makes the gate predicate return False (fail-open). The fail-open posture preserves usability on a half-configured host but means a corrupted multi-user config silently degrades the gate to no-op. Operators relying on this gate as a security control should monitor `config validate`.
- The gate trusts that any prior login document on the current TTY (or the global fallback) belongs to an authorized operator. The launcher does not re-validate the email against the live `people` list before opening the TUI — the identity context does that lookup later on the first protected call. A stale auth document whose email was removed from `people` will pass the gate but fail on the first protected call.
- The launcher kills any existing `tc_tui` tmux session before spawning a new one. This is intentional (only one trusted TUI per host at a time) but means a concurrent invocation will displace an in-progress operator session without warning.
- Environment forwarding into the new tmux session is fail-closed. Only platform-owned TUI runtime keys are propagated; arbitrary shell variables and secrets are never forwarded by configuration.
