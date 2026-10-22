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

It does not re-read the people registry to confirm a carried person identity. An invalid daemon credential resolves no identity and leaves any separately carried identity unchanged.

The daemon credential resolves to the system role without a person email or caller session.

## Canonical fields

### Use cases

#### UC-CV-CARRIED-SESSION: A call carrying a session's identity is taken as carried

#### UC-CV-CARRIED-PERSON: A call carrying a person's identity is taken as carried

#### UC-CV-NO-IDENTITY: A call that carries no identity reaches its operation as a caller with none

#### UC-CV-SIGNALS-NOT-CREDENTIALS: A session token or tmux session on a call resolves nothing

#### UC-CV-OPERATION-CARRIES-CALLER: Work the daemon runs for a caller carries that caller

#### UC-CV-TERMINAL-NO-PERSON

#### UC-CV-DAEMON-SELF: The daemon's own calls resolve to its system principal, never to a person

#### UC-CV-DAEMON-FORGED: A daemon credential the daemon did not mint resolves nothing

#### UC-CV-SESSION-PRINCIPAL-HUMAN

#### UC-CV-SESSION-PRINCIPAL-SYSTEM

#### UC-CV-SESSION-PRINCIPAL-NONE

#### UC-CV-SESSION-OUTRANKS-TERMINAL

### Cross-context references

- Consumed by every operation on the daemon's request surface. An operation that scopes an act to its objects — the session authority rule, reminder ownership, the claiming-group rule, person-bound service selection — evaluates that rule against the returned `CallerIdentity`.
- The identity it takes is produced by the client-side caller resolution and clearance in `local/projects/teleclaude/spec/identity-and-auth` §6 and `feature/identity/command-clearance`; session principals resolve there through `feature/identity/principal-resolution`.
- Reads nothing from the `agent_runtime` or `config` bounded contexts: the carried identity already names the session and the person.
- A request relayed to another computer carries the caller's principal, and that computer decides it — see `feature/identity/cross-computer-authorization`.
- In v2 this collapses into `identity.resolve(headers)` returning a typed `Principal` (or Anonymous).

## Known caveats

- A carried identity is not proven. Any process that can reach the daemon's local socket can carry any identity; the daemon's request surface is not an isolation boundary between local processes (`local/projects/teleclaude/spec/identity-and-auth`, Known caveats).
- The daemon credential is the one value caller verification checks, because it is minted in the daemon's own memory and no other process can produce it.

## See Also

- docs/local/adr/0101-clients-authorize-and-the-daemon-trusts-carried-identity.md — why the daemon takes the carried identity as given.
