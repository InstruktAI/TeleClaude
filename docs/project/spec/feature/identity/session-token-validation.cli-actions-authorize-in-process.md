---
description: 'No request surface validates a session token; a session caller is identified by its session record in the client that serves it.'
visibility: 'public'
---

# Session Token Validation — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

A session token is not a credential any request surface accepts. The daemon issues tokens to system-principal sessions (`feature/identity/session-token-issuance`) and revokes them on termination (`feature/identity/session-token-revocation`), but no call presents one to be validated: the client that serves a caller inside a session identifies it from its session record, reached through the session id its identity document names, and carries the resolved identity on its requests (`project/spec/identity-and-auth` §6); the daemon takes that carried identity as given (`feature/identity/caller-verification`).

## Canonical fields

### Use cases

#### UC-STV1: A token on a call identifies nothing

```
Given a call to the daemon's request surface that presents a session token
When caller verification runs
Then the token is not looked up in the ledger
And the call is taken with the identity it carries, or with none
```

### Cross-context references

- `feature/identity/caller-verification` owns the intake of the identity a call carries.
- `project/spec/identity-and-auth` §6 owns how a client resolves a session caller.

## Known caveats

- The ledger's principal and role columns are written at issuance and read by nothing.
