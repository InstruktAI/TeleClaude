---
description: "Report the caller's identity via `telec auth whoami` — agent sessions resolve through the identity context, terminal sessions read the TTY login."
visibility: 'public'
---

# Whoami Resolution — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

`telec auth whoami` is the operator-facing question "who does the system think I am?". The CLI handler has two paths that mirror v1's two authentication shapes: an agent session (one with a session token in its TMPDIR identity file) queries the identity context's whoami capability and prints the token-stamped Principal and Role; a terminal session (no token) reads its per-TTY auth document and resolves the Role through the human-identity resolver against the `people` config. The whoami capability is itself gated by caller verification, so invoking it inside an agent session also exercises the full token-Resolution path. The CLI accepts a conversational alias — `telec auth who am i` — that rewrites to `telec auth whoami`.

## Canonical fields

### Use cases

```
Given an agent session whose TMPDIR identity file contains `session_token: 8f3c1a7d-2b94-4e6c-9f0e-2a8d7b6c4e5f`
When the operator runs `telec auth whoami`
Then the CLI reads the token via the session-token reader and invokes the identity context's whoami capability over the local transport
And the capability resolves the caller through caller verification (token-path)
And the capability returns `{"principal": "system:c3f1d8a2-7b94-4e6c-9f0e-2a8d7b6c4e5f", "role": "worker"}`
And the CLI prints two lines: `Principal: system:c3f1d8a2-7b94-4e6c-9f0e-2a8d7b6c4e5f` and `Role: worker`
```

```
Given a terminal session with no session token and a TTY auth document holding `maurice@instrukt.ai`
And `people` config maps that email to the `admin` Role
When the operator runs `telec auth whoami`
Then the CLI skips the token branch and reads the email via the session-auth reader
And the role lookup returns `admin`
And the CLI prints `Email: maurice@instrukt.ai`, `Role: admin`, `TTY: <pts/N>`, `Session auth file: <path>`
```

```
Given a terminal session with no session token and no TTY login document
When the operator runs `telec auth whoami`
Then the CLI prints `No login set for current TTY (<tty>).` and exits with success
```

```
Given an environment with no detectable TTY and no session token
When the operator runs `telec auth whoami`
Then the CLI prints `Error: no terminal session detected (TTY unavailable).` and exits with a failure status
```

```
Given any caller resolved by caller verification whose CallerIdentity has principal=`system:8f3c1a7d-2b94-4e6c-9f0e-2a8d7b6c4e5f` and principal_role=`orchestrator`
When the identity context's whoami capability runs
Then it returns `{"principal": "system:8f3c1a7d-2b94-4e6c-9f0e-2a8d7b6c4e5f", "role": "orchestrator"}`
```

```
Given a CallerIdentity with no principal but human_role=`member` (terminal/email path)
When the identity context's whoami capability runs
Then it returns `{"principal": null, "role": "member"}`
```

```
Given a CallerIdentity with no principal and no human_role (e.g. single-user mode anonymous fallback could produce admin; this path covers everything else)
When the identity context's whoami capability runs
Then it returns `{"principal": null, "role": null}`
```

```
Given an operator types `telec auth who am i`
When the auth subcommand dispatcher parses the args
Then the conversational pattern matches and the call is rewritten to `telec auth whoami`
And the standard whoami flow runs
```

### Cross-context references

- The token path reaches transitively into `agent_runtime.sessions` — caller verification loads the session record bound to the token and rejects the call if the session is closed/closing.
- The terminal path reaches into `config.people` via the role lookup. It does not touch the identity context at all; whoami works against the local config even when the identity context is down.
- The whoami capability is itself gated by caller verification, so it is the simplest live exercise of token Resolution end-to-end.
- In v2 this is the same capability spelled as a method on the identity service (`identity.who_am_i(principal)`) returning a typed `Principal` (or Anonymous).

## Known caveats

- The conversational alias is strict: it matches exactly the three tokens `who`, `am`, `i` (the third with optional trailing `?`). Punctuation or different ordering misses and falls through to the unknown-subcommand branch.
- The role lookup returns the string `"unresolved"` on a miss when rendering the terminal output — that is a CLI label, not a Role band. It never appears in a `CallerIdentity.human_role`.
- The token path requires the identity context to be reachable. If it is down, an agent-session whoami fails with an API error — there is no local fallback.
- A token whose session has been closed will fail at caller verification with "session no longer active" BEFORE the whoami capability runs. The CLI surfaces this as a generic error, not as a friendly "logged out" message.
- The token path prints only `Principal` and `Role`. The terminal path prints `Email`, `Role`, `TTY`, and `Session auth file`. The two outputs are intentionally different shapes because they answer different questions about Resolution.
