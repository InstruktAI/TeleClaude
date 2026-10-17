---
description: "Per-session identity file in the session's TMPDIR naming the session its processes belong to; written atomically by the identity context and read by CLI subprocesses to resolve the caller a process inside the session acts as."
visibility: 'public'
---

# Session Identity File — Spec

## Required reads

- @docs/local/spec/domain/identity.md
- @docs/local/spec/identity-and-auth.md

## What it is

The file-based contract that lets any CLI subprocess running inside a TeleClaude session know which session it belongs to without consulting the identity context. Every session has a dedicated TMPDIR (allocated by `agent_runtime`'s tmux bridge); inside that TMPDIR the identity context writes a small structured identity document carrying the session's `session_id` and nothing else. A subprocess inside the session reads that id and resolves everything else it needs — the caller it acts as, its roles, its company — from the session record: identity is resolved at the edge and carried inside, so a process inside a session never consults a terminal login to learn who it is. For identity-context-hosted async tasks that have no TMPDIR of their own, a context-var override lets the operations layer impersonate the originating session's id for the duration of the task. A person-rooted session whose lineage no longer resolves to a registered person carries no person role.

## Canonical fields

### Document contents

The document carries exactly one field: `session_id`. Every other fact about the session — its
principal, its roles, its company — lives on the session record or in its owner's
store and is resolved from `session_id` when a reader needs it. The document never carries a copy
of any of them, so there is nothing in it that can disagree with the record and nothing that has
to be kept in sync with it. The writer replaces the one-field document atomically and requires
owner-only file permissions.

### Use cases

#### UC-SIF1: A person has an agent act under their current identity

```gherkin
Scenario: Use the identity carried by a person-rooted session
  Given a registered person has an agent session rooted at their identity
  When the agent in that session resolves the caller for a TeleClaude command
  Then it acts as that person with the role the registry holds at that time
  And a terminal login does not replace the session identity
  And a role change takes effect on the next resolution

Scenario: An unregistered lineage has no person role
  Given a session lineage no longer resolves to a registered person
  When a process in that session resolves its caller
  Then no person role is assigned
  And no terminal login is consulted
```

#### UC-SIF2: A session with system lineage acts as the system

#### UC-SIF3: A process outside any session is resolved at the edge

#### UC-SIF4: A session identity document that names no usable session fails closed

#### UC-SIF5: A session reads what its recorded identity admits, whatever its document carries

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
- The writer requests mode `0600` on the temporary file before atomically replacing the
  identity document. It ignores an `OSError` from `chmod`, so owner-only permissions
  are not guaranteed if the host refuses the change; the owner-only file mode remains
  the contract. The directory mode is whatever the surrounding TMPDIR provides — this
  snippet does not lock down TMPDIR itself, so a laxly permissioned directory remains
  a defense-in-depth gap on shared hosts.
- The full UUID is written verbatim into the file; readers and consumers must NOT truncate when forwarding the value to logs, signals, or messages (see `docs/local/spec/session-identity-truth.md`).
