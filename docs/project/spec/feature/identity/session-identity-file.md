---
id: project/spec/feature/identity/session-identity-file
type: spec
domain: software-development
scope: project
visibility: public
applies_to: v1
status: actual
description: Per-session `teleclaude_identity.json` in the session's TMPDIR carrying session_id, session_token, system_role, and human_role; written atomically by the daemon, read by CLI subprocesses to populate identity headers.
---

# Session Identity File — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The file-based contract that lets any CLI subprocess running inside a TeleClaude session know which session it belongs to without consulting the daemon. Every session has a dedicated TMPDIR (allocated by `agent_runtime`'s tmux bridge); inside that TMPDIR the daemon writes a small JSON document named `teleclaude_identity.json` carrying four fields — `session_id`, `session_token`, `system_role`, and `human_role`. The bootstrap writer issues a fresh session token for system principals and merges the resulting record into the file; per-field reader helpers expose each value to the CLI without raising on missing or malformed input. Subprocesses inside the session resolve their own identity by inspecting `$TMPDIR/teleclaude_identity.json` and populate `x-session-token`, `x-caller-session-id`, and (via the consumed `system_role`/`human_role` values) the role context on every daemon call. For daemon-hosted async tasks that have no TMPDIR of their own, a context-var override (`get_caller_session_id`) lets the operations layer impersonate the originating session's id for the duration of the task.

## Canonical fields

### Use cases

```
Given a session being bootstrapped with session_id "8c2f6d10-4a3b-4d8f-9b21-7e0f5a1c0e7d"
And the session's TMPDIR is allocated by tmux_bridge.get_session_tmpdir
When ensure_tmux_with_identity calls write_session_identity_to(directory=session_tmp,
   session_id="8c2f6d10-4a3b-4d8f-9b21-7e0f5a1c0e7d",
   session_token=<uuid or None>,
   system_role=<role or None>,
   human_role=<role or None>)
Then teleclaude_identity.json is atomically created at
   <session_tmp>/teleclaude_identity.json with mode 0o600
And the JSON object contains session_id and any non-None token/role fields
And the file is sort_keys=True with a trailing newline
```

```
Given a session whose resolved principal is "system:<session_id>"
When ensure_tmux_with_identity bootstraps the session
Then db.issue_session_token returns a fresh UUID4
And the identity file carries that UUID4 in the session_token field
And the file's system_role mirrors session.system_role (lowercased, stripped)
And the file's human_role mirrors session.human_role
```

```
Given a session whose resolved principal is "human:<email>"
When ensure_tmux_with_identity bootstraps the session
Then no session token is issued (the principal does not start with "system:")
And the identity file is written with session_token absent
And subsequent get_session_token() calls return None
And the session authenticates via x-telec-email + x-caller-session-id instead
```

```
Given an identity file already containing {session_id, session_token}
When a later bootstrap stage calls write_session_identity_to with only system_role set
Then _write_identity_fields merges the new field into the existing record
And the prior session_id and session_token values are preserved
And the merged document is atomically replaced via tmp + os.replace
```

```
Given a CLI subprocess started inside the session's tmux pane (TMPDIR points at the session dir)
When the subprocess calls get_session_id() / get_session_token() / get_system_role() / get_human_role()
Then each helper reads its single field from teleclaude_identity.json and returns its value
And missing fields or a malformed file yield None (helpers never raise)
And empty / whitespace-only string values are coerced to None
```

```
Given the same subprocess making an HTTP call to the daemon
When _build_identity_headers / tool_api_request assembles the request headers
Then x-session-token is set from get_session_token() when present
And x-caller-session-id is set from get_session_id()
And both headers are sent only when the current tmux session is NOT the trusted-TUI session (tc_tui)
And the daemon's verify_caller validates the token first, falling back to the dual-factor session-id path
```

```
Given a daemon-hosted async operation handler executing on behalf of session "8c2f6d10-4a3b-4d8f-9b21-7e0f5a1c0e7d"
And operations.service has called set_caller_session_id("8c2f6d10-4a3b-4d8f-9b21-7e0f5a1c0e7d") on the current context
When the handler calls get_session_id()
Then the context-var override wins over any TMPDIR file
And the override value "8c2f6d10-4a3b-4d8f-9b21-7e0f5a1c0e7d" is returned
And resetting the override via reset_caller_session_id falls back to file lookup
```

```
Given a process with no TMPDIR / TMP / TEMP environment variable
When _identity_path() resolves the file location
Then it returns None
And every reader helper returns None
And write_session_identity (the in-process variant) raises RuntimeError "Cannot write session identity: no TMPDIR set"
```

### Implementation pointers (v1)

- File name and location resolution: `teleclaude/session_identity.py:16-24` (`_IDENTITY_FILENAME`, `_identity_path`)
- Atomic write (tmp + fsync + chmod 0o600 + `os.replace`): `teleclaude/session_identity.py:72-84` (`_atomic_write_identity`)
- Merge-on-write writer (explicit directory): `teleclaude/session_identity.py:104-117` (`write_session_identity_to`)
- Merge-on-write writer (current TMPDIR): `teleclaude/session_identity.py:87-101` (`write_session_identity`)
- Per-field readers (never raise): `teleclaude/session_identity.py:44-69` (`get_session_id`, `get_session_token`, `get_system_role`, `get_human_role`)
- Context-var override for daemon-hosted tasks: `teleclaude/core/operation_caller_identity.py:7-25` (`set_caller_session_id`, `reset_caller_session_id`, `get_caller_session_id`)
- Bootstrap writer (token issuance + identity write): `teleclaude/core/session_bootstrap.py:36-54` (`ensure_tmux_with_identity`)
- TMPDIR allocator (cross-context dependency): `teleclaude.core.tmux_bridge.get_session_tmpdir`
- Header injection (sync CLI): `teleclaude/cli/tool_client.py:85-99`
- Header injection (async CLI): `teleclaude/cli/api_client.py:468-490`

### Cross-context references

- The session TMPDIR itself is allocated by `agent_runtime` via `tmux_bridge.get_session_tmpdir`; this snippet owns the file's contract, not the directory's lifecycle.
- The `session_token` field is produced by `feature/identity/session-token-issuance` (system principals only) and consumed by `feature/identity/session-token-validation` on the daemon side.
- The `session_id` field is the binding key for `feature/identity/caller-verification`'s dual-factor path: the daemon cross-checks the `x-caller-session-id` header against the live `x-tmux-session` name before honoring it.
- `system_role` and `human_role` mirror the columns on the session record (`teleclaude/core/db_models.py`); they are written into the file as a convenience for CLI tools that want to surface the role locally without an extra round-trip — the daemon never trusts a client-supplied role.
- The context-var override (`operation_caller_identity`) is the bridge that lets daemon-hosted async operations (the `operations.service` execution path) carry the originating session's id past the boundary where a TMPDIR no longer exists. Without it, daemon-internal callers would have no `session_id` to present.
- No v1 domain event is emitted by writing the identity file. In v2 the equivalent state change is the materialization of a `SessionPrincipal`, which is recorded inside the identity context but not emitted as its own event (the token-issuance event covers the observable side).

## Known caveats

- The file is process-shared via the environment variable that names the TMPDIR: any subprocess that inherits `TMPDIR` (or its `TMP`/`TEMP` fallbacks) automatically sees the same session identity. Operators who shell into a session's tmux pane and then `unset TMPDIR` will detach the shell from the session's identity even though they are physically inside the session.
- The reader helpers are deliberately total (never raise). A malformed JSON file, a non-dict root, or a non-string field value all degrade to None silently. This is intentional fail-closed behavior — a corrupted file produces an unauthenticated caller rather than a crash — but it means file corruption can masquerade as "no identity" without warning.
- The bootstrap writer merges fields rather than overwriting wholesale (`_write_identity_fields` reads the existing JSON before adding fields). Stages that run after bootstrap can add or update individual fields; they cannot blank out fields written by an earlier stage by passing `None`. To erase a field requires deleting the file.
- The context-var override has priority over the TMPDIR file ONLY for `get_session_id`. The other three helpers (`get_session_token`, `get_system_role`, `get_human_role`) read exclusively from disk. Daemon-hosted code that needs token-level identity must obtain the token from the database or from the session record directly — there is no token override path.
- File mode 0o600 is applied to both the tmp file and the final file, but the directory mode is whatever the surrounding TMPDIR provides — this snippet does not chmod the TMPDIR itself. A laxly permissioned TMPDIR is a defense-in-depth gap on shared hosts.
- The full UUID is written verbatim into the file; readers and consumers must NOT truncate when forwarding the value to logs, headers, or messages (see `docs/project/spec/session-identity-truth.md`).
