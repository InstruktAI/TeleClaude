---
description: "The TUI launches carrying the identity its terminal resolves: the logged-in person, the sole registered person, or, with no login on a multi-user host, the computer's operator."
visibility: 'public'
---

# TUI Multi-User Login Gate — Spec

## Required reads

- @docs/local/spec/domain/identity.md
- @docs/local/spec/identity-and-auth.md

## What it is

The startup-time resolution of the identity the trusted TUI carries. When `telec` is invoked with no arguments — the canonical "open the TUI" entry point — the launcher resolves the terminal's email the way every client does (`feature/identity/terminal-email-login`): the person the current TTY's login names, or the sole registered person. It starts the TUI whether or not an email resolves; no login is required. With an email, the launcher carries it into the TUI; without one, the TUI carries no person and its caller is the computer's operator, `system:operator` (`local/projects/teleclaude/spec/identity-and-auth` §2, §5), cleared as `local/projects/teleclaude/spec/feature/identity/command-clearance` states. The launcher spawns a fresh `tc_tui` tmux session marked with the TUI runtime marker; that marker is what later authorizes the identity context to trust an in-tmux terminal-email signal for the duration of the TUI's lifetime.

An invocation already inside the marked TUI session dispatches in-process without resolving a new launch identity or creating a nested TUI session.

## Canonical fields

### Use cases

#### UC-TUIG1: An operator opens the TUI under the identity of their terminal

```gherkin
Scenario: A multi-user terminal opens the TUI as its selected person
  Given more than one person is registered
  And the operator has signed in on the current terminal
  When they open the TUI
  Then protected TUI actions use the selected person's identity

Scenario: A multi-user terminal without a login opens the TUI as the computer's operator
  Given more than one person is registered
  And the current terminal has no saved login
  When the operator opens the TUI
  Then the TUI starts without requiring a login
  And protected TUI actions are cleared as the computer's operator, naming no person

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

- Resolves the launch identity through the terminal-email resolution of `feature/identity/terminal-email-login`; the people registry decides only whether that email names a person.
- Producer of the trusted-TUI marker (the TUI runtime marker inside tmux session `tc_tui`) consumed by the client-side caller resolution (`local/projects/teleclaude/spec/identity-and-auth` §6) — the TUI's launched identity is honoured only where the marker is present.
- Coordinates with `agent_runtime` insofar as the TUI runs inside a tmux session the launcher creates; the `tc_tui` session is distinct from agent-session tmux names (`tc_<session_id_short>`) and is not part of the managed session table.
- Consumes `feature/identity/terminal-email-login` for the person a launched TUI carries; a login is not a precondition for launching it.
- No v1 domain event is emitted at launch. The behavior is local launcher policy, not an identity-context state change.

## Known caveats

- The launch identity is resolved once, at startup. A login made or removed while the TUI is running does not change the identity it carries — the next TUI launch resolves again.
- The launcher does not re-validate a carried email against the live `people` list before opening the TUI — the identity context does that lookup on each protected call. A stale auth document whose email was removed from `people` carries that email into the TUI, and its protected calls fail as an unresolved login; it never becomes the operator.
- Launching without a login carries the operator's authority. The TUI is no security boundary between people sharing one operating-system account; such an installation needs a separate operating-system user per person.
- The launcher kills any existing `tc_tui` tmux session before spawning a new one. This is intentional (only one trusted TUI per host at a time) but means a concurrent invocation will displace an in-progress operator session without warning.
- Environment forwarding into the new tmux session is fail-closed. Only platform-owned TUI runtime keys are propagated; arbitrary shell variables and secrets are never forwarded by configuration.

## See Also

- docs/local/adr/0152-an-unidentified-local-caller-is-the-computers-operator.md — why a local caller with no identity acts as the computer's operator.
