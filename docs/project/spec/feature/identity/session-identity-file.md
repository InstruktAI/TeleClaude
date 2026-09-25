---
description: "Per-session identity file in the session's TMPDIR naming the session its processes belong to; written atomically by the identity context and read by CLI subprocesses to resolve the caller a process inside the session acts as."
visibility: 'public'
---

# Session Identity File — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

<!-- planned-change:procedure-event-activation -->
The file-based contract that lets any CLI subprocess running inside a TeleClaude session know which session it belongs to without consulting the identity context. Every session has a dedicated TMPDIR (allocated by `agent_runtime`'s tmux bridge); inside that TMPDIR the identity context writes a small structured identity document carrying five fields — `session_id`, `session_token`, `system_role`, `human_role`, and `principal`. The bootstrap writer issues a fresh session token for system principals and merges the resulting record into the file; per-field reader helpers expose each value to the CLI without raising on missing or malformed input. Subprocesses inside the session resolve their own identity by inspecting the file under `$TMPDIR` and populate the session-token and caller-session-id signals on every call into the identity context. The carried `principal` is the identity a process inside the session acts as: identity is resolved at the edge and carried inside, so a process that carries a principal never consults a terminal login to learn who it is. For identity-context-hosted async tasks that have no TMPDIR of their own, a context-var override lets the operations layer impersonate the originating session's id for the duration of the task.
<!-- change:procedure-event-activation -->
The file-based contract that lets any CLI subprocess running inside a TeleClaude session know which session it belongs to without consulting the identity context. Every session has a dedicated TMPDIR (allocated by `agent_runtime`'s tmux bridge); inside that TMPDIR the identity context writes a small structured identity document carrying five identity fields — `session_id`, `session_token`, `system_role`, `human_role`, and `principal` — and the session's company fields: the company, its origin (human-directed or system-principal work), and whether it is resolved, absent, or ambiguous, written from the session record and membership resolution as `project/spec/domain/identity` states. The bootstrap writer issues a fresh session token for system principals and merges the resulting record into the file; per-field reader helpers expose each value to the CLI without raising on missing or malformed input. Subprocesses inside the session resolve their own identity by inspecting the file under `$TMPDIR` and populate the session-token and caller-session-id signals on every call into the identity context. The carried `principal` is the identity a process inside the session acts as: identity is resolved at the edge and carried inside, so a process that carries a principal never consults a terminal login to learn who it is. For identity-context-hosted async tasks that have no TMPDIR of their own, a context-var override lets the operations layer impersonate the originating session's id for the duration of the task.
<!-- /planned-change:procedure-event-activation -->

## Canonical fields

### Use cases

<!-- planned-change:foreign-session-carried-identity -->
```
Given a session being bootstrapped with session_id "8c2f6d10-4a3b-4d8f-9b21-7e0f5a1c0e7d"
And the session's TMPDIR is allocated by `agent_runtime`'s tmux bridge
When the bootstrap writer is called with that session_id and the resolved token / role fields
Then a session-identity document is atomically created inside that TMPDIR with private file mode
And the document contains session_id and any non-None token/role fields
And the document is written with stable key ordering and a trailing newline
```
<!-- change:foreign-session-carried-identity -->
```
Given a session being bootstrapped with session_id "8c2f6d10-4a3b-4d8f-9b21-7e0f5a1c0e7d"
And the session's TMPDIR is allocated by `agent_runtime`'s tmux bridge
When the bootstrap writer is called with that session_id and the session's token, when one is issued
Then a session-identity document is atomically created inside that TMPDIR with private file mode
And the document contains session_id and the token when one is issued
And the document carries no principal and no role
And the document is written with stable key ordering and a trailing newline
```
<!-- /planned-change:foreign-session-carried-identity -->

<!-- planned-change:foreign-session-carried-identity -->
```
Given a session whose resolved principal is "system:daemon"
When the bootstrap writer runs
Then session-token issuance produces a fresh UUID4 (see `feature/identity/session-token-issuance`)
And the identity file carries that UUID4 in the session_token field
And the file's system_role mirrors the session's system_role (lowercased, stripped)
And the file's human_role mirrors the session's human_role
And the file's principal is that system principal
```
<!-- change:foreign-session-carried-identity -->
```
Given a session whose resolved principal is "system:daemon"
When the bootstrap writer runs
Then session-token issuance produces a fresh UUID4 (see `feature/identity/session-token-issuance`)
And the identity file carries that UUID4 in the session_token field
```
<!-- /planned-change:foreign-session-carried-identity -->

<!-- planned-change:foreign-session-carried-identity -->
```
Given a session whose resolved principal is "human:<email>"
When the bootstrap writer runs
Then no session token is issued (the principal does not start with "system:")
And the identity file is written with session_token absent
And subsequent reader calls for the token return None
And the file's principal is that human principal
And the session authenticates via the terminal-email and caller-session-id signals instead
```
<!-- change:foreign-session-carried-identity -->
```
Given a session whose resolved principal is "human:<email>"
When the bootstrap writer runs
Then no session token is issued (the principal does not start with "system:")
And the identity file is written with session_token absent
And subsequent reader calls for the token return None
And the session authenticates via the terminal-email and caller-session-id signals instead
```
<!-- /planned-change:foreign-session-carried-identity -->

<!-- planned-change:foreign-session-carried-identity -->
```
Given an identity file already containing {session_id, session_token}
When a later bootstrap stage writes with only system_role set
Then the writer merges the new field into the existing record
And the prior session_id and session_token values are preserved
And the merged document is atomically replaced
```
<!-- change:foreign-session-carried-identity -->
```
Given an identity file already containing {session_id, session_token}
When a later bootstrap stage writes without a token
Then the writer merges its fields into the existing record
And the prior session_id and session_token values are preserved
And a field the document's contract does not name, such as a principal or role left by an earlier document, is absent afterwards
And the merged document is atomically replaced
```
<!-- /planned-change:foreign-session-carried-identity -->

```
Given a CLI subprocess started inside the session's tmux pane (TMPDIR points at the session dir)
When the subprocess calls any per-field reader helper
Then each helper reads its single field from the identity file and returns its value
And missing fields or a malformed file yield None (helpers never raise)
And empty / whitespace-only string values are coerced to None
```

```
Given a child process inherits the managed session's TMPDIR but has no tmux attachment
When the child invokes an agent hook or TeleClaude CLI client
Then the identity file still establishes the owning TeleClaude session lineage
And the missing tmux attachment classifies the execution as a managed descendant rather than headless
And the child's native session id remains distinct from the owning session id
```

```
Given the same subprocess making a call into the identity context
When the CLI assembles the identity signals
Then the session-token signal is set from the token reader when present
And the caller-session-id signal is set from the session-id reader
And both signals are sent only when the current tmux session is NOT the trusted-TUI session (tc_tui)
And caller verification validates the token first, falling back to the dual-factor session-id path
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

<!-- planned-change:foreign-session-carried-identity -->
```
Given a process with no session identity document present — it runs outside any session
When it resolves the caller it acts as
Then the terminal login is the only source consulted, as for any caller arriving from outside
```
<!-- change:foreign-session-carried-identity -->
```
Given a process with no session identity document present
And no agent harness session id in its environment that names exactly one open session on this computer — it runs outside any session
When it resolves the caller it acts as
Then the terminal login is the only source consulted, as for any caller arriving from outside
```
<!-- /planned-change:foreign-session-carried-identity -->

#### UC-SIF4: A session identity document that names no usable session fails closed

<!-- planned-change:foreign-session-carried-identity -->
```
Given a process whose session identity document is present but malformed, or names a session with no open record on this computer
When the caller resolver decides the caller it acts as
Then it acts as a caller with no identity
And the resolver consults no terminal login, because the document's presence places the process inside a session
```
<!-- change:foreign-session-carried-identity -->
```
Given a process whose session identity document is present but malformed, or names a session with no open record on this computer
When the caller resolver decides the caller it acts as
Then it acts as a caller with no identity
And the resolver consults no terminal login, because the document's presence places the process inside a session
And the resolver consults no agent harness session id in the process's environment
```
<!-- /planned-change:foreign-session-carried-identity -->

#### UC-SIF5: A session reads what its recorded identity admits, whatever its document carries

```
Given an agent working inside a session whose record roots its lineage at a registered person with the admin role
And the session's identity document names that session but carries no principal, or a principal other than the record's
When a process inside that session runs telec docs get on a non-public project snippet
Then the snippet's content is returned
And no "access: denied" notice is shown for it
```
<!-- planned:foreign-session-carried-identity -->

#### UC-SIF6: An agent session TeleClaude did not start acts as the session its hooks recorded

```
Given an agent CLI started outside TeleClaude's launch path — by hand from a terminal, by another agent host, or as a subagent of such an agent
And the agent's hooks have recorded its session, with the person the starting terminal's login names
And a process the agent starts carries no session identity document and carries the agent's own session id in the environment variable its harness sets
When that process resolves the caller it acts as
Then it acts as that recorded session, as a process inside a session TeleClaude started acts as its own (UC-SIF1, UC-SIF2)
And a session-scoped act its role admits succeeds for that session, such as arming the session's own reminder
And no terminal login is consulted
```

#### UC-SIF7: A harness session id that names no single open session leaves the process at the edge

```
Given a process with no session identity document
And the agent harness session ids in its environment name no open session on this computer, or name more than one
When it resolves the caller it acts as
Then it is resolved at the edge from its terminal login, as UC-SIF3 states
And it is never resolved as any of the sessions those ids name
```
<!-- /planned:foreign-session-carried-identity -->

### Cross-context references

- The session TMPDIR itself is allocated by `agent_runtime` via the tmux bridge; this snippet owns the file's contract, not the directory's lifecycle.
- The `session_token` field is produced by `feature/identity/session-token-issuance` (system principals only) and consumed by `feature/identity/session-token-validation` inside the identity context.
- The `session_id` field is the binding key for `feature/identity/caller-verification`'s dual-factor path: the identity context cross-checks the inbound caller-session-id against the live tmux-session signal before honoring it.
<!-- planned-change:foreign-session-carried-identity -->
- `system_role` and `human_role` mirror the columns on the session record; they are written into the file as a convenience for CLI tools that want to surface the role locally without an extra round-trip — the identity context never trusts a client-supplied role.
- `principal` mirrors the principal `feature/identity/principal-resolution` resolves for the session record — its lineage root: the owning person for work with human lineage, the system principal for work without. No caller resolution reads it: a process inside the session resolves the caller it acts as from the session record that `session_id` names, through the same principal resolution the identity context applies, so the document and the identity context cannot disagree about who the session is. A caller's role is read from the people registry when it is needed, never copied here.
<!-- change:foreign-session-carried-identity -->
- The document carries no principal and no role. A process inside the session — the git wrapper and the commit path included — resolves the caller it acts as from the session record that `session_id` names, through the principal resolution the identity context applies (`feature/identity/principal-resolution`), so the document and the identity context cannot disagree about who the session is. A caller's role is read from the people registry when it is needed, never copied here.
- An agent session TeleClaude did not start has no document. Its hooks record the session (`feature/integration/headless-session-bootstrap-from-hook`), and its processes reach that record through the session id their agent harness sets in their environment; the agent registry names that environment variable per agent.
<!-- /planned-change:foreign-session-carried-identity -->
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

- The reader helpers are deliberately total (never raise). A malformed identity file, a non-dict root, or a non-string field value all degrade to None silently. This is intentional fail-closed behavior — a corrupted file produces an unauthenticated caller rather than a crash — but it means file corruption can masquerade as "no identity" without warning.
<!-- planned-change:foreign-session-carried-identity -->
- The bootstrap writer merges fields rather than overwriting wholesale (it reads the existing document before adding fields). Stages that run after bootstrap can add or update individual fields; they cannot blank out fields written by an earlier stage by passing `None`. The one exception is the record rewrite used when a live session's identity changes (startup reconciliation, adoption into a standing role): it writes every identity field from the session record, so a field the record no longer carries — a human role cleared at adoption — is absent afterwards, and it keeps the session's existing token, the one field the record does not hold.
- The context-var override has priority over the TMPDIR file ONLY for the session-id reader. The other readers (token, system_role, human_role) read exclusively from disk; the `principal` field has no reader. Identity-context-hosted code that needs token-level identity must obtain the token from the session store directly — there is no token override path.
<!-- change:foreign-session-carried-identity -->
- The bootstrap writer merges fields rather than overwriting wholesale (it reads the existing document before adding fields). Stages that run after bootstrap can add or update individual fields; they cannot blank out fields written by an earlier stage by passing `None`. The one exception is the record rewrite used when a live session's record changes (startup reconciliation, adoption into a standing role): it writes the document afresh from the session record and keeps the session's existing token, the one field the record does not hold.
- The context-var override has priority over the TMPDIR file ONLY for the session-id reader. The token reader reads exclusively from disk. Identity-context-hosted code that needs token-level identity must obtain the token from the session store directly — there is no token override path.
- An agent harness session id travels through the environment as `TMPDIR` does: any process that carries it, and no session identity document, resolves as the session it names. It is a carried reference, not a credential.
<!-- /planned-change:foreign-session-carried-identity -->
- Private file mode is applied to both the tmp file and the final file, but the directory mode is whatever the surrounding TMPDIR provides — this snippet does not lock down the TMPDIR itself. A laxly permissioned TMPDIR is a defense-in-depth gap on shared hosts.
- The full UUID is written verbatim into the file; readers and consumers must NOT truncate when forwarding the value to logs, signals, or messages (see `docs/project/spec/session-identity-truth.md`).

<!-- planned:foreign-session-carried-identity -->
## See Also

- docs/project/adr/0103-foreign-sessions-are-named-by-their-harness-session-id.md — why a process with no session identity document names its session by the id its harness carries.
<!-- /planned:foreign-session-carried-identity -->
