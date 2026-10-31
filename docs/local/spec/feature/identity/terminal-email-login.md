---
description: 'Bind a human email to the current terminal via `telec auth login`, written to a per-TTY identity file and read by the client to resolve the caller it serves.'
visibility: 'public'
---

# Terminal Email Login — Spec

## Required reads

- @docs/local/spec/domain/identity.md
- @docs/local/spec/identity-and-auth.md

## What it is

The v1 surface that lets a human authenticate to TeleClaude from an interactive terminal — outside of any agent session — by binding an email address to the controlling TTY. `telec auth login <email>` writes a small structured document scoped to the current TTY, and nothing else: there is no machine-global login record. Subsequent `telec` invocations from the same TTY — or from a process with no terminal of its own whose nearest terminal-bearing ancestor runs on that TTY — read the document, and the client resolves the email against the configured `people` list to derive the caller's Principal and role; the resolved person is the identity the client clears and carries on its requests (`local/projects/teleclaude/spec/identity-and-auth` §6). While exactly one person is registered, a terminal with no document of its own resolves to that person. A process inside a session — one whose session identity document is present — reads no terminal login at all: a session carries its own identity, and the terminal login serves only callers arriving from outside. Logout removes the per-TTY document. A successful login also prunes records for terminal devices that have disappeared while leaving live terminals' bindings untouched, including other people's bindings. A terminal that presents no email binds no person; its caller is the computer's operator, whose admission belongs to `local/projects/teleclaude/spec/feature/identity/command-clearance` (`local/projects/teleclaude/spec/identity-and-auth` §2), not to this binding. This is the v1 binding between a real person at a real terminal and the identity context's authorization model. The per-TTY login document is replaced atomically and is intended to remain private to its owner.

## Canonical fields

### Use cases

#### UC-TEL1: An operator binds a terminal to their identity

```gherkin
Scenario: Sign in a terminal as the selected person
  Given an operator has a registered identity and an interactive terminal
  When they sign in on that terminal
  Then commands from the terminal are recognized as that person
  And the login confirms which person was selected
  And the saved terminal binding is private to its owner

Scenario: A recycled terminal does not inherit an old login
  Given a terminal name has been reused for a new device allocation
  And its saved login belongs to the previous allocation
  When the operator runs a TeleClaude command from that terminal
  Then the previous login is not accepted as the terminal's identity

Scenario: Login requires an interactive terminal
  Given a process has no terminal to bind
  When it attempts to sign in
  Then no terminal identity is recorded
  And it is told that a terminal is required
  And the command exits with failure
```

#### UC-TEL2: Login releases documents whose terminal device is gone and leaves live ones alone

#### UC-TEL3: A live per-TTY document answers for its own terminal

#### UC-TEL4: A per-TTY document outlives neither its device nor its allocation

#### UC-TEL5: A sole registered person is recognized on a fresh terminal

```gherkin
Scenario: Recognize the only registered person without another login
  Given exactly one person is registered and the terminal has no saved login
  When the operator starts a TeleClaude command there
  Then the terminal is recognized as that person without another login step

Scenario: No registered person supplies no terminal identity
  Given no person is registered and the terminal has no saved login
  When the operator starts a TeleClaude command there
  Then no person identity is assigned to the terminal
```

#### UC-TEL6: A fresh terminal selects no registered person

```gherkin
Scenario: A fresh multi-user terminal works as no person until a login selects one
  Given more than one person is registered and the terminal has no saved login
  When the operator starts a TeleClaude command there
  Then no person identity is selected
  And the command is decided for a caller that names no person
```

#### UC-TEL7: A process with no terminal presents no human identity

#### UC-TEL8: A process inside a session presents no terminal login

#### UC-TEL9: An operator signs out of the current terminal

```gherkin
Scenario: Sign out one terminal
  Given a terminal has a saved login
  When the operator signs out from that terminal
  Then future commands there no longer use the saved person identity
  And logins on other terminals remain intact
```

### Cross-context references

- Consumes `config.people` (transitively, via the role lookup) to display the matched role at login time. Caller resolution from the login happens in the client that serves the caller — see `local/projects/teleclaude/spec/identity-and-auth` §6.
- Writes operator-local filesystem state under the session-auth directory. No identity-context state is touched by login itself.
- Coordinates with the TUI launcher (`feature/identity/tui-multi-user-login-gate`): the person this login names is the identity a launched TUI carries; a TUI launched without one carries no person.
- The TUI launcher carries the identity it resolved in the outer terminal into the `tc_tui` tmux session alongside the TUI runtime marker, and the reader honours that carried identity only where the marker is present. The marker reaches that session and no other: it is absent from the environment filters that build agent sessions.
- No v1 domain event is emitted by login. In v2 the equivalent action remains a local terminal binding and does not produce an identity event; only `identity.principal.created` is emitted (when a new person is added through config, not at login time).

## Known caveats

- There is no machine-global login record. The registry, not the last terminal someone logged in on, answers who a single-user host belongs to, so a typo'd or since-removed email can never answer for a fresh terminal, and a registry shrinking back to one person never lets one terminal's login speak for every other.
- A process with no terminal of its own borrows the terminal of its nearest terminal-bearing ancestor. An agent CLI started from a terminal runs its tool shells detached from that terminal, yet it acts for the person who started it, so it inherits that terminal's login and loses it when the terminal closes. The daemon itself is rooted in the service manager and has no terminal-bearing ancestor. A session the daemon spawns runs in a tmux pane, which is a terminal, but no process inside a session reads a terminal login: the session carries its identity, so the pane's terminal never answers for it (UC-TEL8). A process that the daemon's own launcher started from a terminal in the foreground would inherit that operator's login; that is the operator at their own keyboard.
- A terminal's login survives another person logging in, because release is keyed on the device rather than on who logged in last. It does not survive the terminal closing: the device node goes with it, and a later terminal that reuses the same name carries a different allocation token and is treated as unauthenticated.
- The terminal-device allocation token is the recycling discriminator, and it is platform-specific because each platform keeps a different attribute stable for exactly one allocation. On macOS it is the device node's inode: devfs issues a fresh inode each time a pty is allocated, while the node's ctime moves on every write to the terminal and so cannot identify an allocation. On Linux it is the device node's ctime: devpts derives the inode from the pty index, so a reused terminal keeps it, while terminal I/O leaves ctime untouched. On Linux, anything that touches the device node's metadata — `mesg y`, for instance — moves ctime; the cost is one re-login on a terminal that is still open. The alternative discriminators require holding the device open, which the release sweep cannot do for terminals it does not own.
- A non-interactive remote invocation (`ssh <host> '<command>'`) has no terminal and therefore presents no person identity. Whether it may run a command is decided for the caller it resolves to (`local/projects/teleclaude/spec/identity-and-auth` §2), never by this binding.

- A document that records no device allocation token cannot satisfy the liveness condition and is treated as no document at all. Recording the device's present allocation token instead would bless a terminal that may already have been recycled, so the document is rejected rather than migrated, and every terminal authenticated before that condition existed authenticates once more.
- Login validation is shallow — empty input and missing `@` are rejected but no RFC-level email validation is performed. A typo'd address is accepted at write time and only surfaces as an unresolved principal when the client tries to match it against `people`.
- A tmux pane is a terminal like any other: login writes a document for it and the reader honours that document on the same device terms as any other terminal, for a process that carries no session identity. A process inside a session reads no terminal login, whichever pane it runs on. The trusted-TUI marker gates one thing only — whether an identity carried in the environment is honoured — and never what a terminal's own document answers.
- A terminal login is a local convenience: it answers only for a client running on this host, and v2 hardens it with an explicit config-gated production toggle (see the Known caveats in `docs/local/spec/domain/identity.md`).
- Legacy plaintext auth documents (a bare email string instead of structured form) are still readable for backward compatibility. There is no automatic rewrite — the document is upgraded only on the next successful login.
- The writer attempts mode `0600` for each login file and `0700` for the
  containing directory but ignores `OSError` from either permission change. If
  the host refuses them, owner-only permissions are not guaranteed even though
  private access remains the contract.
