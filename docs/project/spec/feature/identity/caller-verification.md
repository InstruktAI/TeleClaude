---
id: 'project/spec/feature/identity/caller-verification'
type: 'spec'
domain: 'software-development'
scope: 'project'
visibility: 'public'
applies_to: 'v1'
status: 'actual'
description: 'Resolve every authenticated HTTP request into a `CallerIdentity` via the daemon''s single `verify_caller` dependency.'
---

# Caller Verification — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

The single FastAPI dependency `verify_caller` is v1's Resolution function: it turns the four caller-identity headers carried on every local-socket call into a typed `CallerIdentity` value (the v1 ancestor of v2's `Principal`). Every protected daemon route binds it — directly via `Depends(verify_caller)` or transitively via `require_clearance(...)` — so every authorized operation begins with the same precedence: a session-token check, then a dual-factor session-id + tmux cross-check, then a terminal-email lookup, with a final fallback that either returns an admin-role Anonymous (single-user mode) or raises 401 (multi-user mode). The function answers "who is this caller and what bands do they carry?" before any business logic runs.

## Canonical fields

### Use cases

```
Given an authenticated HTTP request carrying `x-session-token: c3f1d8a2-7b94-4e6c-9f0e-2a8d7b6c4e5f`
When verify_caller runs
Then the token-path branch resolves the token against `db.validate_session_token`
And the session referenced by the token is loaded (cache or DB) and verified open
And the returned CallerIdentity carries the token's principal and principal_role
And the dual-factor session-id branch is not taken
```

```
Given a request with no `x-session-token`, with `x-caller-session-id: 8a2c1f4d-6e0b-4f3a-90ab-5cd7e9b21f3c` and `x-tmux-session: worker-8a2c1f4d`
And the daemon session record stores `tmux_session_name: worker-8a2c1f4d`
When verify_caller runs
Then `_verify_session_identity` confirms the tmux header matches the stored name
And the returned CallerIdentity carries session_id, derived system_role, and resolved human_role
```

```
Given the same request with `x-tmux-session: tc_tui` while the stored tmux_session_name is `worker-8a2c1f4d`
When verify_caller runs
Then `_verify_session_identity` raises HTTPException(403, "session identity mismatch")
```

```
Given a request with no `x-session-token`, no `x-caller-session-id`, and `x-telec-email: maurice@instrukt.ai`
And the global `people` config maps that email to an `admin` Role
When verify_caller runs
Then `_build_terminal_identity` returns a CallerIdentity with no session_id, no system_role, human_role=`admin`, and email recorded
```

```
Given a request with no token, no session id, and an unresolvable `x-telec-email`
And the global `people` config has more than one registered person (multi-user mode)
When verify_caller runs
Then `_build_terminal_identity` raises HTTPException(401, "login required in multi-user mode")
```

```
Given the same unresolved-email request, but the global `people` config has zero or one registered person (single-user mode)
When verify_caller runs
Then `_build_terminal_identity` returns a CallerIdentity with human_role=`admin` (Anonymous-admin fallback)
```

### Implementation pointers (v1)

- Dependency entry point: `teleclaude/api/auth.py:256-293` (`verify_caller`)
- Token-path resolution: `teleclaude/api/auth.py:172-195` (`_verify_token_identity`)
- Dual-factor session-id path with tmux cross-check: `teleclaude/api/auth.py:235-253` (`_verify_session_identity`)
- Terminal-email path with multi-user gate: `teleclaude/api/auth.py:198-222` (`_build_terminal_identity`)
- System-role derivation (explicit column + `working_slug` heuristic): `teleclaude/api/auth.py:130-145` (`_derive_session_system_role`)
- Human-role resolution with terminal-email fallback: `teleclaude/api/auth.py:225-232` (`_resolve_human_role`)
- `CallerIdentity` dataclass: `teleclaude/api/auth.py:148-158`
- Session and token caches (30 s TTL, 256 entries): `teleclaude/api/auth.py:41-107`
- CLI header injection: `teleclaude/cli/api_client.py:468-490` (`_build_identity_headers`) and `teleclaude/cli/tool_client.py:85-99`
- Identity-header trust middleware (rejects `x-web-user-*` from non-localhost): `teleclaude/api_server.py:432-448`

### Cross-context references

- Consumed by every protected daemon route via `Depends(verify_caller)` or `Depends(clearance_*)`. The pre-built `clearance_*` dependencies at `teleclaude/api/auth.py:361-390` all chain through it.
- Reads from `agent_runtime` (sessions, transitively through `db.get_session`) and from `config` (the `IdentityResolver` for email→Role mapping at `teleclaude/core/identity.py`).
- The `x-session-token` branch interlocks with session-token issuance — see `feature/identity/session-token-issuance` and `feature/identity/session-token-validation`. The derived system_role is the same value `resolve_session_principal` would stamp on a token — see `feature/identity/principal-resolution`.
- In v2 this collapses into `identity.resolve(headers)` returning a typed `Principal` (or Anonymous); the v2 model unifies token-auth, session-id-auth, and email-trust under one resolution call.

## Known caveats

- The tmux cross-check is conditional. `_verify_session_identity` only raises 403 when BOTH `x-tmux-session` AND `session.tmux_session_name` are present and differ. A request with no `x-tmux-session` header (or a session record with no stored tmux name) passes the check silently. This is intentional — daemon-spawned tasks without a tmux pane must still authenticate — but it weakens the dual-factor property for that subset of callers.
- The session and token caches have a 30-second TTL. A freshly closed session can resolve briefly through the cache; `invalidate_session_cache` / `invalidate_token_cache` are called on session close to mitigate, but a race window exists.
- The terminal-email fallback in single-user mode stamps `admin` even when no email is present. This is the v1 single-user convenience — it is explicitly NOT how v2 will behave (v2 returns Anonymous and lets the caller decide).
- `_derive_session_system_role` falls back to the heuristic "if `working_slug` is set, treat as worker" when `system_role` is unset. A row with a stale `working_slug` would mis-band as worker. The column-first ordering protects current deployments.
- The CLI's `tool_client.py` and `api_client.py` deliberately suppress token/session-id headers when the tmux session name is `tc_tui` (the trusted TUI). TUI callers ALWAYS go the terminal-email path even though they live in tmux.
