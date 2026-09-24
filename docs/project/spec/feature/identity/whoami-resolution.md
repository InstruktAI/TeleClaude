---
description: "Report the caller's identity via `telec auth whoami`."
visibility: 'public'
---

# Whoami Resolution — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

`telec auth whoami` is the operator-facing question "who does the system think I am?". Inside a session and at a terminal alike, the CLI queries the identity context's whoami capability and prints what caller verification resolved for the identity signals it sends. Inside a session — one whose TMPDIR holds a session identity document — it prints the Principal and Role its session resolves to, whether it presents a session token or its session id, and never reads the terminal login; a document that is present but unusable is reported and nothing is asked. Outside any session it prints the Email and Role of the person the terminal's login names, followed by the TTY and the login document's path; the CLI resolves no Role itself. The whoami capability is gated by caller verification, so every invocation exercises the full caller-verification path. The CLI accepts a conversational alias — `telec auth who am i` — that rewrites to `telec auth whoami`.

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
Given a terminal outside any session — no session identity document — whose login document names `ada@example.com`
And the `people` registry holds `ada@example.com` with the `admin` Role
When the operator runs `telec auth whoami`
Then the CLI sends that login as its identity signal to the identity context's whoami capability
And it prints `Email: ada@example.com` and `Role: admin` from the capability's answer, then `TTY: <pts/N>` and `Session auth file: <path>`
And the CLI resolves no Role itself
```

```
Given a terminal outside any session that caller verification cannot identify — no login document on a host with more than one registered person, or a login naming no registered person
When the operator runs `telec auth whoami`
Then the CLI prints that no identity is established for the current TTY, with the refusal's instruction to log in, and exits with success
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

```
Given an operator types `telec auth who am i`
When the auth subcommand dispatcher parses the args
Then the conversational pattern matches and the call is rewritten to `telec auth whoami`
And the standard whoami flow runs
```

### Cross-context references

- The token path reaches transitively into `agent_runtime.sessions` — caller verification loads the session record bound to the token and rejects the call if the session is closed/closing.
- Every path reaches the identity context: the person and role printed at a terminal are the ones caller verification resolves, from the `people` registry, for the login the terminal presents. The CLI resolves no role itself.
- The whoami capability is itself gated by caller verification, so it is the simplest live exercise of token Resolution end-to-end.
- In v2 this is the same capability spelled as a method on the identity service (`identity.who_am_i(principal)`) returning a typed `Principal` (or Anonymous).

## Known caveats

- The conversational alias is strict: it matches exactly the three tokens `who`, `am`, `i` (the third with optional trailing `?`). Punctuation or different ordering misses and falls through to the unknown-subcommand branch.
- Every whoami requires the identity context to be reachable. If it is down, whoami fails with an API error — there is no local fallback, at a terminal or inside a session.
- A token whose session has been closed will fail at caller verification with "session no longer active" BEFORE the whoami capability runs. The CLI surfaces this as a generic error, not as a friendly "logged out" message.
- The token path prints only `Principal` and `Role`. The terminal path prints `Email`, `Role`, `TTY`, and `Session auth file`. The two outputs are intentionally different shapes because they answer different questions about Resolution.
