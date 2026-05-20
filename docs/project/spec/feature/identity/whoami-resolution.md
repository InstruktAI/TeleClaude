---
id: 'project/spec/feature/identity/whoami-resolution'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Report the caller''s identity via `telec auth whoami` — agent sessions resolve through the daemon, terminal sessions read the TTY login.'
---

# Whoami Resolution — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

`telec auth whoami` is the operator-facing question "who does the system think I am?". The CLI handler has two paths that mirror v1's two authentication shapes: an agent session (one with a session token in its TMPDIR identity file) calls the daemon's `GET /auth/whoami` endpoint over the local socket and prints the token-stamped Principal and Role; a terminal session (no token) reads its per-TTY auth file and resolves the Role through the `IdentityResolver` against the `people` config. The endpoint itself is gated by `verify_caller`, so calling it inside an agent session also exercises the full token-Resolution path. The CLI accepts a conversational alias — `telec auth who am i` — that rewrites to `telec auth whoami`.

## Canonical fields

### Use cases

```
Given an agent session whose TMPDIR identity file contains `session_token: 8f3c1a7d-2b94-4e6c-9f0e-2a8d7b6c4e5f`
When the operator runs `telec auth whoami`
Then `_handle_whoami` reads the token via `get_session_token()` and calls `api.get_auth_whoami()` over the daemon socket
And the daemon endpoint resolves the caller through `verify_caller` (token-path)
And the endpoint returns `{"principal": "system:c3f1d8a2-7b94-4e6c-9f0e-2a8d7b6c4e5f", "role": "worker"}`
And the CLI prints two lines: `Principal: system:c3f1d8a2-7b94-4e6c-9f0e-2a8d7b6c4e5f` and `Role: worker`
```

```
Given a terminal session with no session token and a TTY auth file holding `maurice@instrukt.ai`
And `people` config maps that email to the `admin` Role
When the operator runs `telec auth whoami`
Then `_handle_whoami` skips the token branch and reads the email via `read_current_session_email`
And `_role_for_email` returns `admin`
And the CLI prints `Email: maurice@instrukt.ai`, `Role: admin`, `TTY: <pts/N>`, `Session auth file: <path>`
```

```
Given a terminal session with no session token and no TTY login file
When the operator runs `telec auth whoami`
Then `_handle_whoami` prints `No login set for current TTY (<tty>).` and exits 0
```

```
Given an environment with no detectable TTY and no session token
When the operator runs `telec auth whoami`
Then `_handle_whoami` prints `Error: no terminal session detected (TTY unavailable).` and exits 1
```

```
Given any caller resolved by verify_caller whose CallerIdentity has principal=`system:8f3c1a7d-2b94-4e6c-9f0e-2a8d7b6c4e5f` and principal_role=`orchestrator`
When the daemon serves `GET /auth/whoami`
Then the endpoint returns `{"principal": "system:8f3c1a7d-2b94-4e6c-9f0e-2a8d7b6c4e5f", "role": "orchestrator"}`
```

```
Given a CallerIdentity with no principal but human_role=`member` (terminal/email path)
When the daemon serves `GET /auth/whoami`
Then the endpoint returns `{"principal": null, "role": "member"}`
```

```
Given a CallerIdentity with no principal and no human_role (e.g. single-user mode anonymous fallback could produce admin; this path covers everything else)
When the daemon serves `GET /auth/whoami`
Then the endpoint returns `{"principal": null, "role": null}`
```

```
Given an operator types `telec auth who am i`
When `_handle_auth` parses the args
Then the conversational pattern matches and the call is rewritten to `telec auth whoami`
And the standard whoami flow runs
```

### Implementation pointers (v1)

- CLI handler: `teleclaude/cli/telec/handlers/auth_cmds.py:106-153` (`_handle_whoami`)
- Conversational alias rewrite: `teleclaude/cli/telec/handlers/auth_cmds.py:40-42`
- TTY-side role lookup: `teleclaude/cli/telec/handlers/auth_cmds.py:59-70` (`_role_for_email`)
- Server endpoint: `teleclaude/api_server.py:466-479` (`auth_whoami` route handler)
- Token reader: `teleclaude/session_identity.py:57-59` (`get_session_token`)
- Per-TTY email reader: `teleclaude/cli/session_auth.py` (`read_current_session_email`, called at `auth_cmds.py:144`)
- Client wrapper that hits the endpoint: `teleclaude/cli/api_client.py:635` (`TelecAPIClient.get_auth_whoami`)

### Cross-context references

- The token path reaches transitively into `agent_runtime.sessions` — `verify_caller` loads the session record bound to the token and rejects the call if the session is closed/closing.
- The terminal path reaches into `config.people` via `_role_for_email`. It does not touch the daemon at all; whoami works against the local config even when the daemon socket is down.
- The endpoint is itself gated by `verify_caller`, so it is the simplest live exercise of token Resolution end-to-end.
- In v2 this is the same function spelled as a method on the identity service (`identity.who_am_i(principal)`) returning a typed `Principal` (or Anonymous).

## Known caveats

- The conversational alias is strict: it matches exactly the three tokens `who`, `am`, `i` (the third with optional trailing `?`). Punctuation or different ordering misses and falls through to the unknown-subcommand branch.
- `_role_for_email` returns the string `"unresolved"` on a miss when rendering the terminal output — that is a CLI label, not a Role band. It never appears in a `CallerIdentity.human_role`.
- The token path requires the daemon socket. If the daemon is down, an agent-session whoami exits 1 with an `APIError` — there is no local fallback.
- A token whose session has been closed will fail at `verify_caller` with `HTTPException(401, "session no longer active")` BEFORE the endpoint runs. The CLI surfaces this as a generic error, not as a friendly "logged out" message.
- The token path prints only `Principal` and `Role`. The terminal path prints `Email`, `Role`, `TTY`, and `Session auth file`. The two outputs are intentionally different shapes because they answer different questions about Resolution.
