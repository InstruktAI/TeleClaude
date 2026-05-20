---
id: 'project/spec/feature/identity/terminal-email-login'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Bind a human email to the current terminal via `telec auth login`, written to a per-TTY identity file and injected as `x-telec-email` on outbound API calls.'
---

# Terminal Email Login — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The v1 surface that lets a human authenticate to TeleClaude from an interactive terminal — outside of any agent session — by binding an email address to the controlling TTY. `telec auth login <email>` writes a small JSON file scoped to the current TTY (with a global fallback when no TTY is detectable) and a duplicate "last login wins" record at `global_identity.json`. Subsequent `telec` invocations from the same TTY read the file and inject the email into outbound daemon calls as the `x-telec-email` header, where the daemon's `verify_caller` path resolves it against the configured `people` list to derive a Principal and role. Logout deletes the per-TTY file but deliberately leaves the global fallback intact. This is the v1 binding between a real person at a real terminal and the daemon's authorization model.

## Canonical fields

### Use cases

```
Given an interactive terminal with a detectable controlling TTY (e.g. /dev/ttys003)
And the operator runs `telec auth login alice@example.com`
When write_current_session_email normalizes and validates the address
Then a JSON payload {email, tty, updated_at} is atomically written to
   $TELECLAUDE_HOME/session-auth/ttys003.json with mode 0o600
And the same payload is also written to
   $TELECLAUDE_HOME/session-auth/global_identity.json (last-login-wins fallback)
And the CLI prints "Logged in as alice@example.com[ (<role>)]." plus the TTY and file path
```

```
Given a person whose email is listed under `people` in the global teleclaude.yml
When `telec auth login` resolves their role via _role_for_email
Then the login banner appends the matched role in parentheses
And a missing or unmatched email still completes login but prints no role suffix
```

```
Given an input lacking an "@" sign or containing only whitespace
When write_current_session_email normalizes the value
Then a ValueError "A valid email address is required." is raised
And the CLI prints the error and exits with status 1
And no file is written
```

```
Given a subsequent telec invocation from the same TTY as the prior login
When the CLI builds outbound identity headers
Then read_current_session_email returns the per-TTY email first
And the HTTP request carries x-telec-email: <email>
And the daemon resolves the principal via the terminal-email auth path
```

```
Given a process with no detectable TTY (no ttyname on fd 0/1/2 and no SSH_TTY)
When the same flow runs
Then login writes only the global_identity.json file
And read_current_session_email falls back to that global record
```

```
Given a legacy auth file containing a bare email string (pre-JSON format)
When _read_auth_file parses it
Then the raw text is normalized (lowercased, trimmed) and returned as the email
And the legacy file remains readable without rewrite
```

```
Given a logged-in TTY
When the operator runs `telec auth logout`
Then clear_current_session_email deletes the per-TTY file only
And the global_identity.json fallback is preserved
And the CLI prints "Cleared login for TTY <tty>." (or a "not found" notice)
```

### Implementation pointers (v1)

- Per-TTY write: `teleclaude/cli/session_auth.py:133-165` (`write_current_session_email`)
- Atomic file write (mode 0o600 via tmp + fsync + `os.replace`): `teleclaude/cli/session_auth.py:114-130` (`_write_auth_file`)
- Read with per-TTY → global fallback: `teleclaude/cli/session_auth.py:97-111` (`read_current_session_email`)
- TTY detection (fd 0/1/2 → `SSH_TTY` env): `teleclaude/cli/session_auth.py:39-46` (`_detect_tty`)
- Logout (per-TTY only): `teleclaude/cli/session_auth.py:168-182` (`clear_current_session_email`)
- Login handler / role lookup: `teleclaude/cli/telec/handlers/auth_cmds.py:82-103` (`_handle_login`)
- Role lookup against config.people: `teleclaude/cli/telec/handlers/auth_cmds.py:59-70` (`_role_for_email`)
- Auth file directory: `teleclaude/paths.py:30` (`SESSION_AUTH_DIR = TELECLAUDE_HOME / "session-auth"`)
- Header injection (sync CLI): `teleclaude/cli/tool_client.py:88-97`
- Header injection (async CLI): `teleclaude/cli/api_client.py:483-485`

### Cross-context references

- Consumes `config.people` (transitively, via `_role_for_email`) to display the matched role at login time. Identity resolution itself happens daemon-side from the `x-telec-email` header — see `feature/identity/principal-resolution` and `feature/identity/caller-verification`.
- Writes operator-local filesystem state under `SESSION_AUTH_DIR` (`$TELECLAUDE_HOME/session-auth/`). No daemon state is touched by login itself.
- Coordinates with the TUI launcher: a successful login is the precondition for `feature/identity/tui-multi-user-login-gate` when more than one person is configured.
- The same email is also bridged into the trusted `tc_tui` tmux session via the `TELEC_AUTH_EMAIL` environment variable propagated by the launcher; daemon trust of in-tmux email is gated by the trusted-TUI marker (`TELEC_TUI_SESSION=1` plus tmux session name `tc_tui`).
- No v1 domain event is emitted by login. In v2 the equivalent action remains a local terminal binding and does not produce an identity event; only `identity.principal.created` is emitted (when a new person is added through config, not at login time).

## Known caveats

- The global_identity.json fallback is "last-login-wins" by design: a fresh login from any TTY (or from a no-TTY context) overwrites the global record. Operators sharing a host should not rely on the global file to remember a previous identity; it reflects only the most recent login on the machine.
- `telec auth logout` deliberately does NOT remove the global fallback. After logout from a specific TTY, other TTYs without their own per-TTY file will continue to read the prior global identity. Operators who want a clean wipe must delete `global_identity.json` manually.
- Login validation is shallow — `_normalize_email` rejects empty input and missing `@` but performs no RFC-level email validation. A typo'd address is accepted at write time and only surfaces as an unresolved principal when the daemon tries to match it against `people`.
- Inside a generic tmux session (one that is not the trusted TUI), login still WRITES the file, but the daemon refuses to honor `x-telec-email` from that context — trust is contingent on the trusted-TUI marker (`TELEC_TUI_SESSION=1` and tmux session `tc_tui`). The auth file is technically present but functionally inert from inside an untrusted tmux pane.
- The `x-telec-email` header is intended as a development/local convenience and is honored only when the daemon is bound to a local socket; v2 hardens this with an explicit config-gated production toggle (see the Known caveats in `docs/project/spec/domain/identity.md`).
- Legacy plaintext auth files (a bare email string instead of JSON) are still readable for backward compatibility. There is no automatic rewrite — the file is upgraded only on the next successful login.
