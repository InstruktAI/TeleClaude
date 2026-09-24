---
description: "Report the caller's identity via `telec auth whoami`."
visibility: 'public'
---

# Whoami Resolution — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

`telec auth whoami` is the operator-facing question "who does the system think I am?". The CLI handler has two paths. A process inside a session — one whose TMPDIR holds a session identity document — queries the identity context's whoami capability and prints the Principal and Role its session resolves to, whether it presents a session token or its session id; it never reads the terminal login. A process outside any session reads its per-TTY auth document and resolves the Role through the human-identity resolver against the `people` config. The whoami capability is itself gated by caller verification, so invoking it inside an agent session also exercises the full caller-verification path. The CLI accepts a conversational alias — `telec auth who am i` — that rewrites to `telec auth whoami`.

<!-- planned:external-session-identity -->
### Attested self-identification

#### UC-WHO-ATTESTED: A tokenless caller in an externally hosted session is told which session it is

```gherkin
Given a process inside an agent session the daemon did not launch, holding no session token
And that session's root process instance occurs in the caller's verified ancestry
When the operator runs `telec auth whoami`
Then the CLI queries the identity context over the local transport rather than reading the TTY
And the answer names the session the attested branch resolved, with its Principal and Role
And the per-TTY login identity is not printed as that session's identity
```

#### UC-WHO-UNATTESTED: A caller whose session cannot be proven gets the terminal answer, not a session

```gherkin
Given a tokenless caller for whom the attested branch resolves no session
When the operator runs `telec auth whoami`
Then the CLI falls through to the per-TTY auth document
And the answer identifies a human and claims no session
```

<!-- /planned:external-session-identity -->

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
Given a terminal outside any session — no session identity document — with a TTY auth document holding `maurice@instrukt.ai`
And `people` config maps that email to the `admin` Role
When the operator runs `telec auth whoami`
Then the CLI skips the session branch and reads the email via the session-auth reader
And the role lookup returns `admin`
And the CLI prints `Email: maurice@instrukt.ai`, `Role: admin`, `TTY: <pts/N>`, `Session auth file: <path>`
```

```
Given a terminal outside any session with no TTY login document
When the operator runs `telec auth whoami`
Then the CLI prints `No login set for current TTY (<tty>).` and exits with success
```

```
Given an environment outside any session with no detectable TTY
When the operator runs `telec auth whoami`
Then the CLI prints `Error: no terminal session detected (TTY unavailable).` and exits with a failure status
```

#### UC-WHO-SESSION-CARRIED: Inside a session, whoami reports the identity the session carries

```
Given a process inside a session whose identity document holds no session token — a session whose lineage roots at a person
And the pane it runs on carries a live login document for someone else
When the operator runs `telec auth whoami`
Then the CLI invokes the identity context's whoami capability over the local transport
And it prints the Principal and Role the session resolves to
And the terminal's login is not printed
```

#### UC-WHO-SESSION-UNUSABLE: A session identity document that identifies nothing is reported, not replaced

```
Given a process whose session identity document is present but malformed, or carries no session id
When the operator runs `telec auth whoami`
Then the CLI reports that the session carries no usable identity and exits with a failure status
And no terminal login is consulted or printed
```

<!-- planned-change:cli-authorization-reads-via-daemon -->
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
<!-- change:cli-authorization-reads-via-daemon -->
#### UC-WHO-CAPABILITY-SESSION: The capability answers a session caller with its principal and session

```
Given an agent in a session whose carried principal is `system:daemon` and whose system role is `orchestrator`
When the identity context's whoami capability runs for that caller
Then it returns the principal `system:daemon`, the role `orchestrator`, no email, and the id of the session it verified
```

#### UC-WHO-CAPABILITY-PERSON: The capability answers a person with a principal named for them

```
Given a caller the platform resolves as the registered person `ada@example.com`, whose registered role is `member` — at a terminal, or through a session whose lineage roots at them
When the identity context's whoami capability runs for that caller
Then it returns the principal `human:ada@example.com`, the role `member`, and the email `ada@example.com`
And it returns a session id only when the caller is a session
```

#### UC-WHO-CAPABILITY-NOBODY: The capability attributes nothing it cannot attribute

```
Given a verified session caller that resolves to no person and carries no principal
When the identity context's whoami capability runs for that caller
Then it returns no principal, no role, and no email
```
<!-- /planned-change:cli-authorization-reads-via-daemon -->

```
Given an operator types `telec auth who am i`
When the auth subcommand dispatcher parses the args
Then the conversational pattern matches and the call is rewritten to `telec auth whoami`
And the standard whoami flow runs
```

### Cross-context references

- The token path reaches transitively into `agent_runtime.sessions` — caller verification loads the session record bound to the token and rejects the call if the session is closed/closing.
<!-- planned-change:cli-authorization-reads-via-daemon -->
- The terminal path reaches into `config.people` via the role lookup. It does not touch the identity context at all; whoami works against the local config even when the identity context is down.
<!-- change:cli-authorization-reads-via-daemon -->
- Every path reaches the identity context: the person and role printed at a terminal are the ones caller verification resolves, from the `people` registry, for the login the terminal presents. The CLI resolves no role itself.
<!-- /planned-change:cli-authorization-reads-via-daemon -->
- The whoami capability is itself gated by caller verification, so it is the simplest live exercise of token Resolution end-to-end.
- In v2 this is the same capability spelled as a method on the identity service (`identity.who_am_i(principal)`) returning a typed `Principal` (or Anonymous).

## Known caveats

- The conversational alias is strict: it matches exactly the three tokens `who`, `am`, `i` (the third with optional trailing `?`). Punctuation or different ordering misses and falls through to the unknown-subcommand branch.
<!-- planned-change:cli-authorization-reads-via-daemon -->
- The role lookup returns the string `"unresolved"` on a miss when rendering the terminal output — that is a CLI label, not a Role band. It never appears in a `CallerIdentity.human_role`.
- The token path requires the identity context to be reachable. If it is down, an agent-session whoami fails with an API error — there is no local fallback.
<!-- change:cli-authorization-reads-via-daemon -->
- Every whoami requires the identity context to be reachable. If it is down, whoami fails with an API error — there is no local fallback, at a terminal or inside a session.
<!-- /planned-change:cli-authorization-reads-via-daemon -->
- A token whose session has been closed will fail at caller verification with "session no longer active" BEFORE the whoami capability runs. The CLI surfaces this as a generic error, not as a friendly "logged out" message.
- The token path prints only `Principal` and `Role`. The terminal path prints `Email`, `Role`, `TTY`, and `Session auth file`. The two outputs are intentionally different shapes because they answer different questions about Resolution.
