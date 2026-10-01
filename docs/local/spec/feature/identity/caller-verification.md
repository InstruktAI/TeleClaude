---
description: "Turn the identity every inbound call carries into a `CallerIdentity` via the identity context's single caller-verification capability, without re-verifying it."
visibility: 'public'
---

# Caller Verification — Spec

## Required reads

- @docs/local/spec/domain/identity.md
- @docs/local/spec/identity-and-auth.md

## What it is

Caller verification is the identity context's single intake capability at the daemon's request surface: it turns the identity an inbound call carries into a typed `CallerIdentity` value (the v1 ancestor of v2's `Principal`) before any business logic runs. The client that sent the call has already resolved and cleared its caller in its own process (`local/projects/teleclaude/spec/identity-and-auth` §6) and carries the result — the caller's session, principal, system role, person role, person email, entry point, and session company when present (`local/projects/teleclaude/spec/identity-and-auth` §2). Caller verification takes those values as given. It loads no session to confirm them, resolves no terminal signal, compares no tmux session, validates no session token, and applies no role band; a call that carries no identity yields a `CallerIdentity` with none, and the operation it reaches decides what a caller without identity may do. The one credential it checks is the daemon's own process-local credential, which resolves the daemon's calls to its system principal.

## Canonical fields

### Use cases

#### UC-CV-CARRIED-SESSION: A call carrying a session's identity is taken as carried

```
Given a client resolved its caller to a session and carries that session, its principal, and its system role on a call
When caller verification runs
Then the returned CallerIdentity carries that session, principal, and system role
And when the session has a company, it carries that company as business context
And no session record is loaded to confirm them
And no terminal, tmux, or token signal is consulted
```

#### UC-CV-CARRIED-PERSON: A call carrying a person's identity is taken as carried

```
Given a client at a terminal, or the TUI, resolved its caller to a registered person and carries that person's principal, email, and role on a call
When caller verification runs
Then the returned CallerIdentity carries that principal, email, and role, and no session
And the people registry is not consulted to confirm them
```

#### UC-CV-NO-IDENTITY: A call that carries no identity reaches its operation as a caller with none

```
Given a call that carries no caller identity and no daemon credential
When caller verification runs
Then the call is not refused by caller verification
And the returned CallerIdentity carries no session, no principal, and no role
And an operation that acts only for a calling session refuses the caller itself
```

#### UC-CV-SIGNALS-NOT-CREDENTIALS: A session token or tmux session on a call resolves nothing

```
Given a call that presents a session token or a tmux session name alongside, or instead of, a carried identity
When caller verification runs
Then neither value is consulted
And the returned CallerIdentity is exactly the carried identity, or none
```

#### UC-CV-OPERATION-CARRIES-CALLER: Work the daemon runs for a caller carries that caller

```
Given the daemon accepted a request from a session and runs work for it after the request returns
When that work makes a request to the daemon's request surface
Then the request carries the identity of the session that asked
And it carries that session's company when one is recorded
And the work is attributed to that session, never to the daemon's own principal or a terminal login
```

#### UC-CV-TERMINAL-NO-PERSON

#### UC-CV-DAEMON-SELF: The daemon's own calls resolve to its system principal, never to a person

```
Given a call carrying the daemon's process-local credential and no session-token or caller-session-id
When caller verification runs
Then the returned CallerIdentity carries the daemon's system principal and the system role
And it carries no email and no session id
And the terminal-email branch is not taken
```

#### UC-CV-DAEMON-FORGED: A daemon credential the daemon did not mint resolves nothing

```
Given a call from outside the daemon process carrying a daemon-credential value the daemon did not mint
When caller verification runs
Then the credential resolves no identity
And the returned CallerIdentity is the identity the call carries, or none
```

#### UC-CV-SESSION-PRINCIPAL-HUMAN

#### UC-CV-SESSION-PRINCIPAL-SYSTEM

#### UC-CV-SESSION-PRINCIPAL-NONE

#### UC-CV-SESSION-OUTRANKS-TERMINAL

### Cross-context references

- Consumed by every operation on the daemon's request surface. An operation that scopes an act to its objects — the session authority rule, reminder ownership, the claiming-group rule, person-bound service selection — evaluates that rule against the returned `CallerIdentity`.
- The identity it takes is produced by the client-side caller resolution and clearance in `local/projects/teleclaude/spec/identity-and-auth` §6 and `feature/identity/command-clearance`; session principals resolve there through `feature/identity/principal-resolution`.
- Reads nothing from the `agent_runtime` or `config` bounded contexts: the carried identity already names the session and the person.
- A remote peer receives the caller the local daemon took, carried on the relay — see `feature/session_mirrors/cross-computer-history-federation`.
- In v2 this collapses into `identity.resolve(headers)` returning a typed `Principal` (or Anonymous).

## Known caveats

- A carried identity is not proven. Any process that can reach the daemon's local socket can carry any identity; the daemon's request surface is not an isolation boundary between local processes (`local/projects/teleclaude/spec/identity-and-auth`, Known caveats).
- The daemon credential is the one value caller verification checks, because it is minted in the daemon's own memory and no other process can produce it.

## See Also

- docs/local/adr/0101-clients-authorize-and-the-daemon-trusts-carried-identity.md — why the daemon takes the carried identity as given.
