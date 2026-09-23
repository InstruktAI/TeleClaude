---
description: 'Bind a human email to the current terminal via `telec auth login`, written to a per-TTY identity file and injected as the terminal-email signal on outbound calls into the identity context.'
visibility: 'public'
---

# Terminal Email Login — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The v1 surface that lets a human authenticate to TeleClaude from an interactive terminal — outside of any agent session — by binding an email address to the controlling TTY. `telec auth login <email>` writes a small structured document scoped to the current TTY, and nothing else: there is no machine-global login record. Subsequent `telec` invocations from the same TTY — or from a process with no terminal of its own whose nearest terminal-bearing ancestor runs on that TTY — read the document and inject the email into outbound calls into the identity context as the terminal-email signal, where caller verification resolves it against the configured `people` list to derive a Principal and role. While exactly one person is registered, a terminal with no document of its own resolves to that person. Logout removes the per-TTY document. This is the v1 binding between a real person at a real terminal and the identity context's authorization model.

## Canonical fields

### Use cases

#### UC-TEL1: Login records the terminal device's allocation identity alongside the email

```
Given an interactive terminal with a detectable controlling TTY (e.g. /dev/ttys003)
And the operator runs `telec auth login alice@example.com`
When the login writer normalizes and validates the address
Then a structured payload carrying the email, the terminal device, the write time, and the device's current allocation token is atomically written to the per-TTY auth location with private file mode
And the CLI prints "Logged in as alice@example.com[ (<role>)]." plus the TTY and file path
```

```
Given a process with no terminal of its own, no SSH_TTY, and no ancestor process with a terminal
When it runs `telec auth login alice@example.com`
Then no document is written
And the CLI reports that no terminal was detected and exits with a failure status
```

#### UC-TEL2: Login releases documents whose terminal device is gone and leaves live ones alone

```
Given per-TTY login documents exist for several terminals
And the device node of some of those terminals no longer exists
When any operator completes `telec auth login`
Then every per-TTY document whose device node no longer exists is removed
And every per-TTY document whose device node still exists is left untouched, including documents belonging to another person
```

```
Given a person whose email is listed under `people` in the global config
When `telec auth login` resolves their role
Then the login banner appends the matched role in parentheses
And a missing or unmatched email still completes login but prints no role suffix
```

```
Given an input lacking an "@" sign or containing only whitespace
When the login writer normalizes the value
Then a validation error "A valid email address is required." is raised
And the CLI prints the error and exits with a failure status
And no file is written
```

#### UC-TEL3: A live per-TTY document answers for its own terminal

```
Given a telec invocation from a TTY whose per-TTY login document records the device's current allocation token
When the CLI builds outbound identity signals
Then the session-auth reader returns that document's email
And the outbound call carries the terminal-email signal
And the identity context resolves the principal via the terminal-email auth path
```

#### UC-TEL4: A per-TTY document outlives neither its device nor its allocation

```
Given a per-TTY login document whose terminal device no longer exists, or exists with a different allocation token than the one recorded at login
When the CLI builds outbound identity signals from that TTY
Then the session-auth reader does not return that document's email
And the terminal is treated as carrying no login document of its own
```

#### UC-TEL5: The sole registered person answers a fresh terminal

```
Given a telec invocation from a TTY that carries no login document of its own
And exactly one person is registered
When the CLI builds outbound identity signals
Then the session-auth reader returns that person's email from the people registry
And the human is spared logging in on a shell they just opened
```

```
Given a telec invocation from a TTY that carries no login document of its own
And no person is registered
When the CLI builds outbound identity signals
Then the session-auth reader returns no email
```

#### UC-TEL6: A fresh terminal must authenticate once more than one person is registered

```
Given a telec invocation from a TTY that carries no login document of its own
And more than one person is registered
When the CLI builds outbound identity signals
Then the session-auth reader returns no email
And the outbound call carries no terminal-email signal
And the operator is told that login is required before the command can proceed
```

#### UC-TEL7: A process with no terminal presents no human identity

```
Given a process with no detectable TTY (no ttyname on fd 0/1/2, no SSH_TTY, and no ancestor process with a terminal)
When it builds outbound identity signals
Then the session-auth reader returns no email
And the outbound call carries no terminal-email signal
And this holds for the daemon and every process it spawns
```

```
Given a process with no terminal on fd 0/1/2 and no SSH_TTY
And an ancestor process runs on a terminal (e.g. an agent CLI started from /dev/ttys003 running a detached tool shell)
When it builds outbound identity signals
Then the session-auth reader resolves the nearest such ancestor's terminal
And reads that terminal's login document on the same liveness terms as the terminal itself
And the email it returns is that terminal's human identity, never a session identity
```

```
Given a legacy auth document containing a bare email string (pre-structured format)
When the reader parses it
Then the raw text is normalized (lowercased, trimmed) and returned as the email
And the legacy document remains readable without rewrite
```

```
Given a logged-in TTY
When the operator runs `telec auth logout`
Then the per-TTY auth document is removed
And the CLI prints "Cleared login for TTY <tty>." (or a "not found" notice)
```

### Cross-context references

- Consumes `config.people` (transitively, via the role lookup) to display the matched role at login time. Identity resolution itself happens inside the identity context from the terminal-email signal — see `feature/identity/principal-resolution` and `feature/identity/caller-verification`.
- Writes operator-local filesystem state under the session-auth directory. No identity-context state is touched by login itself.
- Coordinates with the TUI launcher: a successful login is the precondition for `feature/identity/tui-multi-user-login-gate` when more than one person is configured.
- The TUI launcher carries the identity it resolved in the outer terminal into the `tc_tui` tmux session alongside the TUI runtime marker, and the reader honours that carried identity only where the marker is present. The marker reaches that session and no other: it is absent from the environment filters that build agent sessions.
- No v1 domain event is emitted by login. In v2 the equivalent action remains a local terminal binding and does not produce an identity event; only `identity.principal.created` is emitted (when a new person is added through config, not at login time).

## Known caveats

- There is no machine-global login record. The registry, not the last terminal someone logged in on, answers who a single-user host belongs to, so a typo'd or since-removed email can never answer for a fresh terminal, and a registry shrinking back to one person never lets one terminal's login speak for every other.
- A process with no terminal of its own borrows the terminal of its nearest terminal-bearing ancestor. An agent CLI started from a terminal runs its tool shells detached from that terminal, yet it acts for the person who started it, so it inherits that terminal's login and loses it when the terminal closes. The daemon and everything it spawns are rooted in the service manager and have no terminal-bearing ancestor, so they present no human identity. A process that the daemon's own launcher started from a terminal in the foreground would inherit that operator's login; that is the operator at their own keyboard.
- A terminal's login survives another person logging in, because release is keyed on the device rather than on who logged in last. It does not survive the terminal closing: the device node goes with it, and a later terminal that reuses the same name carries a different allocation token and is treated as unauthenticated.
- The terminal-device allocation token is the recycling discriminator, and it is platform-specific because each platform keeps a different attribute stable for exactly one allocation. On macOS it is the device node's inode: devfs issues a fresh inode each time a pty is allocated, while the node's ctime moves on every write to the terminal and so cannot identify an allocation. On Linux it is the device node's ctime: devpts derives the inode from the pty index, so a reused terminal keeps it, while terminal I/O leaves ctime untouched. On Linux, anything that touches the device node's metadata — `mesg y`, for instance — moves ctime; the cost is one re-login on a terminal that is still open. The alternative discriminators require holding the device open, which the release sweep cannot do for terminals it does not own.
- A non-interactive remote invocation (`ssh <host> '<command>'`) has no terminal and therefore no identity. It is not a supported way to run an identity-bearing command.
- A document that records no device allocation token cannot satisfy the liveness condition and is treated as no document at all. Recording the device's present allocation token instead would bless a terminal that may already have been recycled, so the document is rejected rather than migrated, and every terminal authenticated before that condition existed authenticates once more.
- Login validation is shallow — empty input and missing `@` are rejected but no RFC-level email validation is performed. A typo'd address is accepted at write time and only surfaces as an unresolved principal when the identity context tries to match it against `people`.
- A tmux pane is a terminal like any other: login writes a document for it and the reader honours that document on the same device terms as any other terminal. The trusted-TUI marker gates one thing only — whether an identity carried in the environment is honoured — and never what a terminal's own document answers.
- The terminal-email signal is intended as a development/local convenience and is honored only when the identity context is bound to a local-socket transport; v2 hardens this with an explicit config-gated production toggle (see the Known caveats in `docs/project/spec/domain/identity.md`).
- Legacy plaintext auth documents (a bare email string instead of structured form) are still readable for backward compatibility. There is no automatic rewrite — the document is upgraded only on the next successful login.
