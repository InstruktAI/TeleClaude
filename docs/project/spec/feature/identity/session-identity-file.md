---
description: "Per-session identity file in the session's TMPDIR naming the session its processes belong to; written atomically by the identity context and read by CLI subprocesses to resolve the caller a process inside the session acts as."
visibility: 'public'
---

# Session Identity File — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The file-based contract that lets any CLI subprocess running inside a TeleClaude session know which session it belongs to without consulting the identity context. Every session has a dedicated TMPDIR (allocated by `agent_runtime`'s tmux bridge); inside that TMPDIR the identity context writes a small structured identity document carrying the session's `session_id` and nothing else. A subprocess inside the session reads that id and resolves everything else it needs — the caller it acts as, its roles, its company — from the session record: identity is resolved at the edge and carried inside, so a process inside a session never consults a terminal login to learn who it is. For identity-context-hosted async tasks that have no TMPDIR of their own, a context-var override lets the operations layer impersonate the originating session's id for the duration of the task.

## Canonical fields

### Document contents

The document carries exactly one field: `session_id`. Every other fact about the session — its
principal, its roles, its company — lives on the session record or in its owner's
store and is resolved from `session_id` when a reader needs it. The document never carries a copy
of any of them, so there is nothing in it that can disagree with the record and nothing that has
to be kept in sync with it.


### Use cases

```
Given a session being bootstrapped with session_id "8c2f6d10-4a3b-4d8f-9b21-7e0f5a1c0e7d"
And the session's TMPDIR is allocated by `agent_runtime`'s tmux bridge
When the bootstrap writer is called with that session_id
Then a session-identity document is atomically created inside that TMPDIR with private file mode
And the document contains session_id and nothing else, whatever the session's principal or roles
And the document is written with stable key ordering and a trailing newline
```

```
Given a live session whose identity document carries fields besides session_id
When the document is next written
Then it contains session_id and nothing else
```

```
Given a CLI subprocess started inside the session's tmux pane (TMPDIR points at the session dir)
When the subprocess reads the session id from the identity file
Then it receives the session_id value
And a missing field or a malformed file yields None (the reader never raises)
And an empty or whitespace-only value is coerced to None
```

```
Given a child process inherits the managed session's TMPDIR but has no tmux attachment
When the child invokes an agent hook or TeleClaude CLI client
Then the identity file still establishes the owning TeleClaude session lineage
And the missing tmux attachment classifies the execution as a managed descendant rather than headless
And the child's native session id remains distinct from the owning session id
```


```
Given an identity-context-hosted async operation handler executing on behalf of session "8c2f6d10-4a3b-4d8f-9b21-7e0f5a1c0e7d"
And the operations layer has set the caller-session-id context-var override to that session_id
When the handler calls the session-id reader
Then the context-var override wins over any TMPDIR file
And the override value is returned
And resetting the override falls back to file lookup
```

```
Given a process with no TMPDIR / TMP / TEMP environment variable
When the file-location resolver runs
Then it returns None
And every reader helper returns None
And the in-process writer raises a runtime error "Cannot write session identity: no TMPDIR set"
```

#### UC-SIF1: A session with human lineage acts as its person

```
Given an agent working inside a session whose lineage roots at a registered person
When a process inside that session resolves the caller it acts as
Then it acts as that person, with the role the people registry holds for them at that moment
And a change to that person's role takes effect on the next resolution
And no terminal login is consulted
And a lineage root that matches no registered person yields a caller with no role
```

#### UC-SIF2: A session with system lineage acts as the system

```
Given an agent working inside a session whose lineage roots at a system principal — a standing role, or a session one started
When a process inside that session resolves the caller it acts as
Then it acts as that system principal
And what it may do is what its system role permits, with no person's role applying
And no terminal login is consulted
```

#### UC-SIF3: A process outside any session is resolved at the edge

```
Given a process with no session identity document present — it runs outside any session
When it resolves the caller it acts as
Then the terminal login is the only source consulted, as for any caller arriving from outside
```

#### UC-SIF4: A session identity document that names no usable session fails closed

```
Given a process whose session identity document is present but malformed, or names a session with no open record on this computer
When the caller resolver decides the caller it acts as
Then it acts as a caller with no identity
And the resolver consults no terminal login, because the document's presence places the process inside a session
```

#### UC-SIF5: A session reads what its recorded identity admits, whatever its document carries

```
Given an agent working inside a session whose record roots its lineage at a registered person with the admin role
And the session's identity document names that session but carries no principal, or a principal other than the record's
When a process inside that session runs telec docs get on a non-public project snippet
Then the snippet's content is returned
And no "access: denied" notice is shown for it
```

### Cross-context references

- The session TMPDIR itself is allocated by `agent_runtime` via the tmux bridge; this snippet owns the file's contract, not the directory's lifecycle.
- A process inside the session — the git wrapper and the commit path included — resolves the caller it acts as from the session record that `session_id` names, through the principal resolution the identity context applies (`feature/identity/principal-resolution`), and reads a person's role from the people registry when it is needed.
- The context-var override is the bridge that lets identity-context-hosted async operations carry the originating session's id past the boundary where a TMPDIR no longer exists. Without it, internally-spawned callers would have no `session_id` to present.
- No v1 domain event is emitted by writing the identity file. In v2 the equivalent state change is the materialization of a `SessionPrincipal`, which is recorded inside the identity context but not emitted as its own event (the token-issuance event covers the observable side).

## Known caveats

- The file is process-shared via the environment variable that names the TMPDIR: any subprocess that inherits `TMPDIR` (or its `TMP`/`TEMP` fallbacks) automatically sees the same session identity. Operators who shell into a session's tmux pane and then `unset TMPDIR` will detach the shell from the session's identity even though they are physically inside the session.

- Marker presence and marker validity are distinct states. A present but malformed
  identity document fails closed as a managed identity error; consumers that decide
  session creation must not reinterpret it as marker absence.
- Inheriting the identity file transfers lineage, not primary-process status. A
  descendant process keeps its own native execution identity and cannot refresh the
  owning session's canonical native binding merely by emitting hooks.

- The session-id reader is deliberately total (never raises). A malformed identity file, a non-dict root, or a non-string value all degrade to None silently. This is intentional fail-closed behavior — a corrupted file produces an unauthenticated caller rather than a crash — but it means file corruption can masquerade as "no identity" without warning.
- Nothing rewrites the document to keep it in step with the session record: it holds only the session id, which does not change for the life of the session. A change to a session's principal, roles or company — at adoption into a standing role, for example — takes effect for every reader at its next resolution.
- The context-var override takes priority over the TMPDIR file for the session-id reader, the only reader the document has.
- Private file mode is applied to both the tmp file and the final file, but the directory mode is whatever the surrounding TMPDIR provides — this snippet does not lock down the TMPDIR itself. A laxly permissioned TMPDIR is a defense-in-depth gap on shared hosts.
- The full UUID is written verbatim into the file; readers and consumers must NOT truncate when forwarding the value to logs, signals, or messages (see `docs/project/spec/session-identity-truth.md`).
