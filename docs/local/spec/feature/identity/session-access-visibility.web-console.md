---
description: "Authorize session-scoped operations for every person, on every client, against the session owner, the session's shared or private visibility, and the person's scoped role in the session's project."
visibility: 'public'
---

# Session Access & Visibility — Spec

## Required reads

- @docs/local/spec/domain/identity.md
- @docs/local/spec/identity-and-auth.md

## What it is

The per-session authorization rule for people. It applies to every person who
reaches the daemon with carried identity, whichever client carried it — the web
service, the TUI or `telec` — so two clients never show one person two
different sets of sessions. Every operation that targets a session, and every
listing that returns sessions, applies it. The rule reads three facts: the
session's owner, the session's `visibility` (`private` or `shared`), and the
person's scoped role in the session's project, resolved from the carried
principal by the one shared role resolver.

- The **owner** and an **admin** of the project may see the session and perform
  every operation on it, ending it included.
- A **member** of the project may see the session and perform standard
  operations on it — read messages, send a message or keys, restart or revive
  the agent, tail, stream — only when its visibility is `shared`. Ending a
  session is never a member's.
- A **customer**, and anyone with no role in the project, has no access through
  `shared`.
- A session the person may not see is reported as not found, so existence is
  not disclosed by the error type.

Agent and system callers — a session acting through its own identity marker, or
the daemon's own principal — are governed by caller verification's lineage rules
and not by this check.

`shared` is the cooperation primitive: the owner's explicit statement that
teammates may read and act on the session. Without it every session is private
to its owner and the project's admins.

## Canonical fields

### Use cases

```
Given a person whose scoped role in project P is admin
And a session in P owned by anyone
When any session-scoped operation checks access
Then the check admits the person
And the operation proceeds
```

```
Given a person whose scoped role in project P is member
And a session in P owned by that person
When the person ends the session
Then the check admits the person as owner
And the session is closed
```

```
Given a person whose scoped role in project P is member
And a session in P owned by someone else with visibility shared
When the person sends a message to the session
Then the check admits the person on the member-and-shared branch
And the message is dispatched
```

```
Given a person whose scoped role in project P is member
And a session in P owned by someone else with visibility shared
When the person ends the session
Then the check refuses as "Forbidden: not session owner"
And the session stays open
```

```
Given a person whose scoped role in project P is member
And a session in P owned by someone else with visibility private
When the person reads the session's messages
Then the check reports the session as not found
```

```
Given a person whose scoped role in project P is customer
And a session in P with visibility shared
When the person sends a message to the session
Then the check reports the session as not found
Because shared admits members, not customers
```

```
Given a person reaching the daemon through the web service
And the same person reaching it through the TUI
When each client lists sessions
Then both listings contain exactly the sessions this rule admits for that person
```

```
Given a session id that exists in neither cache nor session store
When the check runs for any person
Then the check reports the session as not found
```

### Cross-context references

- `human_email` and `visibility` are owned by `agent_runtime`'s session store;
  `visibility` is set by the session owner, and the identity context reads it
  without writing. `human_email` is stamped at session creation.
- The transport on which carried identity is honoured is
  `feature/identity/identity-header-trust-boundary`; this spec decides what the
  identity unlocks once admitted.
- Caller verification decides who is calling; this check decides which sessions
  that caller may touch. The scoped role comes from the shared role resolver at
  the scope of the session's project.
- The listing rule and the single-session rule are one rule. The API server's
  viewer-authorized projection — HTTP session reads, the connection snapshot and
  incremental session changes — applies it for collections; a divergence between
  a listing and a single-session check is a security defect.
- The web service applies the same decision in-process to filter what it passes
  to a browser and to attach permitted actions to each session
  (`local/projects/teleclaude/design/architecture/web-console`).

## Known caveats

- A session record without a `visibility` value is treated as `private`.
- Ownership compares the stamped `human_email` with the person's email; stamping
  normalizes casing, and the check relies on that rather than normalizing again.
- The check reads the session store after a cache miss; on hot paths the cache
  hit rate decides whether it becomes a store read per call.
