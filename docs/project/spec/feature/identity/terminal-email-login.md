---
description: 'Bind a human email to the current terminal via `telec auth login`, written to a per-TTY identity file and injected as the terminal-email signal on outbound calls into the identity context.'
visibility: 'public'
---

# Terminal Email Login — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The v1 surface that lets a human authenticate to TeleClaude from an interactive terminal — outside of any agent session — by binding an email address to the controlling TTY. `telec auth login <email>` writes a small structured document scoped to the current TTY (with a global fallback when no TTY is detectable) and a duplicate "last login wins" record at a global-identity location. Subsequent `telec` invocations from the same TTY read the document and inject the email into outbound calls into the identity context as the terminal-email signal, where caller verification resolves it against the configured `people` list to derive a Principal and role. Logout removes the per-TTY document but deliberately leaves the global fallback intact. This is the v1 binding between a real person at a real terminal and the identity context's authorization model.

## Canonical fields

### Use cases

```
Given an interactive terminal with a detectable controlling TTY (e.g. /dev/ttys003)
And the operator runs `telec auth login alice@example.com`
When the login writer normalizes and validates the address
Then a structured payload {email, tty, updated_at} is atomically written to the per-TTY auth location with private file mode
And the same payload is also written to a global-identity fallback location (last-login-wins)
And the CLI prints "Logged in as alice@example.com[ (<role>)]." plus the TTY and file path
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

```
Given a subsequent telec invocation from the same TTY as the prior login
When the CLI builds outbound identity signals
Then the session-auth reader returns the per-TTY email first
And the outbound call carries the terminal-email signal
And the identity context resolves the principal via the terminal-email auth path
```

```
Given a process with no detectable TTY (no ttyname on fd 0/1/2 and no SSH_TTY)
When the same flow runs
Then login writes only the global-identity fallback document
And the session-auth reader falls back to that global record
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
And the global-identity fallback is preserved
And the CLI prints "Cleared login for TTY <tty>." (or a "not found" notice)
```

### Cross-context references

- Consumes `config.people` (transitively, via the role lookup) to display the matched role at login time. Identity resolution itself happens inside the identity context from the terminal-email signal — see `feature/identity/principal-resolution` and `feature/identity/caller-verification`.
- Writes operator-local filesystem state under the session-auth directory. No identity-context state is touched by login itself.
- Coordinates with the TUI launcher: a successful login is the precondition for `feature/identity/tui-multi-user-login-gate` when more than one person is configured.
- The same email is also bridged into the trusted `tc_tui` tmux session via a TUI runtime environment variable propagated by the launcher; the identity context's trust of in-tmux email is gated by the trusted-TUI marker (a TUI runtime marker plus tmux session name `tc_tui`).
- No v1 domain event is emitted by login. In v2 the equivalent action remains a local terminal binding and does not produce an identity event; only `identity.principal.created` is emitted (when a new person is added through config, not at login time).

## Known caveats

- The global-identity fallback is "last-login-wins" by design: a fresh login from any TTY (or from a no-TTY context) overwrites the global record. Operators sharing a host should not rely on the global file to remember a previous identity; it reflects only the most recent login on the machine.
- `telec auth logout` deliberately does NOT remove the global fallback. After logout from a specific TTY, other TTYs without their own per-TTY document will continue to read the prior global identity. Operators who want a clean wipe must remove the global-identity document manually.
- Login validation is shallow — empty input and missing `@` are rejected but no RFC-level email validation is performed. A typo'd address is accepted at write time and only surfaces as an unresolved principal when the identity context tries to match it against `people`.
- Inside a generic tmux session (one that is not the trusted TUI), login still WRITES the document, but the identity context refuses to honor the terminal-email signal from that context — trust is contingent on the trusted-TUI marker (TUI runtime marker plus tmux session `tc_tui`). The auth document is technically present but functionally inert from inside an untrusted tmux pane.
- The terminal-email signal is intended as a development/local convenience and is honored only when the identity context is bound to a local-socket transport; v2 hardens this with an explicit config-gated production toggle (see the Known caveats in `docs/project/spec/domain/identity.md`).
- Legacy plaintext auth documents (a bare email string instead of structured form) are still readable for backward compatibility. There is no automatic rewrite — the document is upgraded only on the next successful login.
