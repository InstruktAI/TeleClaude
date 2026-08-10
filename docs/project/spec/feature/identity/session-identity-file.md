---
description: "Per-session identity file in the session's TMPDIR carrying session_id, session_token, system_role, and human_role; written atomically by the identity context, read by CLI subprocesses to populate identity signals."
visibility: 'public'
---

# Session Identity File — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The file-based contract that lets any CLI subprocess running inside a TeleClaude session know which session it belongs to without consulting the identity context. Every session has a dedicated TMPDIR (allocated by `agent_runtime`'s tmux bridge); inside that TMPDIR the identity context writes a small structured identity document carrying four fields — `session_id`, `session_token`, `system_role`, and `human_role`. The bootstrap writer issues a fresh session token for system principals and merges the resulting record into the file; per-field reader helpers expose each value to the CLI without raising on missing or malformed input. Subprocesses inside the session resolve their own identity by inspecting the file under `$TMPDIR` and populate the session-token, caller-session-id, and (via the consumed `system_role`/`human_role` values) the role context on every call into the identity context. For identity-context-hosted async tasks that have no TMPDIR of their own, a context-var override lets the operations layer impersonate the originating session's id for the duration of the task.

## Canonical fields

### Use cases

```
Given a session being bootstrapped with session_id "8c2f6d10-4a3b-4d8f-9b21-7e0f5a1c0e7d"
And the session's TMPDIR is allocated by `agent_runtime`'s tmux bridge
When the bootstrap writer is called with that session_id and the resolved token / role fields
Then a session-identity document is atomically created inside that TMPDIR with private file mode
And the document contains session_id and any non-None token/role fields
And the document is written with stable key ordering and a trailing newline
```

```
Given a session whose resolved principal is "system:<session_id>"
When the bootstrap writer runs
Then session-token issuance produces a fresh UUID4 (see `feature/identity/session-token-issuance`)
And the identity file carries that UUID4 in the session_token field
And the file's system_role mirrors the session's system_role (lowercased, stripped)
And the file's human_role mirrors the session's human_role
```

```
Given a session whose resolved principal is "human:<email>"
When the bootstrap writer runs
Then no session token is issued (the principal does not start with "system:")
And the identity file is written with session_token absent
And subsequent reader calls for the token return None
And the session authenticates via the terminal-email and caller-session-id signals instead
```

```
Given an identity file already containing {session_id, session_token}
When a later bootstrap stage writes with only system_role set
Then the writer merges the new field into the existing record
And the prior session_id and session_token values are preserved
And the merged document is atomically replaced
```

```
Given a CLI subprocess started inside the session's tmux pane (TMPDIR points at the session dir)
When the subprocess calls any per-field reader helper
Then each helper reads its single field from the identity file and returns its value
And missing fields or a malformed file yield None (helpers never raise)
And empty / whitespace-only string values are coerced to None
```

<!-- planned:preserve-managed-descendant-session-identity -->

```
Given a child process inherits the managed session's TMPDIR but has no tmux attachment
When the child invokes an agent hook or TeleClaude CLI client
Then the identity file still establishes the owning TeleClaude session lineage
And the missing tmux attachment classifies the execution as a managed descendant rather than headless
And the child's native session id remains distinct from the owning session id
```

<!-- /planned:preserve-managed-descendant-session-identity -->

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

### Cross-context references

- The session TMPDIR itself is allocated by `agent_runtime` via the tmux bridge; this snippet owns the file's contract, not the directory's lifecycle.
- The `session_token` field is produced by `feature/identity/session-token-issuance` (system principals only) and consumed by `feature/identity/session-token-validation` inside the identity context.
- The `session_id` field is the binding key for `feature/identity/caller-verification`'s dual-factor path: the identity context cross-checks the inbound caller-session-id against the live tmux-session signal before honoring it.
- `system_role` and `human_role` mirror the columns on the session record; they are written into the file as a convenience for CLI tools that want to surface the role locally without an extra round-trip — the identity context never trusts a client-supplied role.
- The context-var override is the bridge that lets identity-context-hosted async operations carry the originating session's id past the boundary where a TMPDIR no longer exists. Without it, internally-spawned callers would have no `session_id` to present.
- No v1 domain event is emitted by writing the identity file. In v2 the equivalent state change is the materialization of a `SessionPrincipal`, which is recorded inside the identity context but not emitted as its own event (the token-issuance event covers the observable side).

## Known caveats

- The file is process-shared via the environment variable that names the TMPDIR: any subprocess that inherits `TMPDIR` (or its `TMP`/`TEMP` fallbacks) automatically sees the same session identity. Operators who shell into a session's tmux pane and then `unset TMPDIR` will detach the shell from the session's identity even though they are physically inside the session.

<!-- planned:preserve-managed-descendant-session-identity -->

- Marker presence and marker validity are distinct states. A present but malformed
  identity document fails closed as a managed identity error; consumers that decide
  session creation must not reinterpret it as marker absence.
- Inheriting the identity file transfers lineage, not primary-process status. A
  descendant process keeps its own native execution identity and cannot refresh the
  owning session's canonical native binding merely by emitting hooks.

<!-- /planned:preserve-managed-descendant-session-identity -->

- The reader helpers are deliberately total (never raise). A malformed identity file, a non-dict root, or a non-string field value all degrade to None silently. This is intentional fail-closed behavior — a corrupted file produces an unauthenticated caller rather than a crash — but it means file corruption can masquerade as "no identity" without warning.
- The bootstrap writer merges fields rather than overwriting wholesale (it reads the existing document before adding fields). Stages that run after bootstrap can add or update individual fields; they cannot blank out fields written by an earlier stage by passing `None`. To erase a field requires deleting the file.
- The context-var override has priority over the TMPDIR file ONLY for the session-id reader. The other three readers (token, system_role, human_role) read exclusively from disk. Identity-context-hosted code that needs token-level identity must obtain the token from the session store directly — there is no token override path.
- Private file mode is applied to both the tmp file and the final file, but the directory mode is whatever the surrounding TMPDIR provides — this snippet does not lock down the TMPDIR itself. A laxly permissioned TMPDIR is a defense-in-depth gap on shared hosts.
- The full UUID is written verbatim into the file; readers and consumers must NOT truncate when forwarding the value to logs, signals, or messages (see `docs/project/spec/session-identity-truth.md`).
