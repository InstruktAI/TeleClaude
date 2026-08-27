---
description: An agent session hosted outside the daemon's own launch flow carries a resolvable session-scoped caller identity, so authenticated operations resolve to that session instead of failing closed or borrowing the machine-global last-login identity.
delivered_by:
  - external-session-identity
---

# Headless Session Identity — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

An agent session hosted outside the daemon's own launch flow — a foreign
harness, a scheduled run, a manual agent CLI invocation — carries a session
identity the identity context can verify, for the life of the session,
inherited by every process the session spawns. Authenticated operations —
arming a reminder, a sealed commit, dispatching a review — resolve to the
session itself, with the same fail-closed guarantees managed sessions have. An
identity claim the platform cannot verify is rejected; the machine-global
last-login identity, which names a human without naming any calling session,
never stands in for a session identity on a session-scoped operation.

## Canonical fields

### Use cases

#### UC-HSI1: An externally hosted session performs authenticated operations as itself

```gherkin
Given an agent session hosted outside the daemon's own launch flow
And the session carries an established session identity
When a process inside the session invokes an authenticated session-scoped operation (such as arming a reminder, making a sealed commit, or dispatching a review)
Then the caller resolves to that session's own identity
And the operation proceeds under that session's principal and role
```

#### UC-HSI2: Self-identification names the session, not the machine's last login

```gherkin
Given an agent session hosted outside the daemon's own launch flow
And the session carries an established session identity
When a process inside the session asks the platform who the caller is
Then the answer names the session-scoped principal
And the machine-global last-login identity is not reported as the caller
```

#### UC-HSI3: An unverifiable session identity claim fails closed

```gherkin
Given a process presents a session identity claim the platform cannot verify against its own records
When that process invokes an authenticated session-scoped operation
Then the call is rejected as unauthenticated
And the machine-global last-login identity does not stand in for the session identity
```

#### UC-HSI4: Child processes inherit the owning session's identity

```gherkin
Given an externally hosted agent session with an established session identity
When the agent spawns a child process (a subagent, a hook receiver, a CLI subprocess)
Then the child's authenticated calls resolve to the same owning session identity
And the child's own native execution identity does not mint a second session
```

## Known caveats

- Establishing session identity does not make the session supervised: the
  daemon still cannot reattach to or manage an agent CLI process it did not
  launch. Identity and supervision remain independent properties.

## See Also

- docs/project/spec/feature/identity/caller-verification.md — how identity signals resolve into a CallerIdentity.
- docs/project/spec/feature/identity/session-identity-file.md — the identity contract daemon-launched sessions receive at bootstrap.
- docs/project/spec/feature/integration/headless-session-bootstrap-from-hook.md — how an externally started agent CLI gains a session record.
- docs/project/spec/session-identity-truth.md — the route classification that distinguishes managed, descendant, and headless invocations.
