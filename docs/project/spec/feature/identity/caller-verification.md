---
description: "Resolve every authenticated inbound call into a `CallerIdentity` via the identity context's single caller-verification capability."
visibility: 'public'
---

# Caller Verification — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

Caller verification is the identity context's single resolution capability: it turns the four caller-identity signals carried on every authenticated inbound call into a typed `CallerIdentity` value (the v1 ancestor of v2's `Principal`). Every authorized operation begins with the same precedence — a session-token check, then a dual-factor session-id + tmux cross-check, then a terminal-email lookup, with a final fallback that either returns an admin-role Anonymous (single-user mode) or rejects the caller as unauthenticated (multi-user mode). The capability answers "who is this caller and what bands do they carry?" before any business logic runs.

## Canonical fields

### Use cases

```
Given an authenticated call carrying a session-token signal `c3f1d8a2-7b94-4e6c-9f0e-2a8d7b6c4e5f`
When caller verification runs
Then the token-path branch resolves the token against the session-token ledger
And the session referenced by the token is loaded and verified open
And the returned CallerIdentity carries the token's principal and principal_role
And the dual-factor session-id branch is not taken
```

```
Given a call with no session-token signal, with caller-session-id `8a2c1f4d-6e0b-4f3a-90ab-5cd7e9b21f3c` and tmux-session signal `worker-8a2c1f4d`
And the identity context's session record stores `tmux_session_name: worker-8a2c1f4d`
When caller verification runs
Then the dual-factor branch confirms the tmux signal matches the stored name
And the returned CallerIdentity carries session_id, derived system_role, and resolved human_role
```

```
Given the same call with tmux-session signal `tc_tui` while the stored tmux_session_name is `worker-8a2c1f4d`
When caller verification runs
Then the dual-factor branch rejects the call as a session-identity mismatch
```

```
Given a call with no session-token, no caller-session-id, and a terminal-email signal `maurice@instrukt.ai`
And the configured `people` list maps that email to an `admin` Role
When caller verification runs
Then the terminal-identity branch returns a CallerIdentity with no session_id, no system_role, human_role=`admin`, and email recorded
```

```
Given a call with no token, no session id, and an unresolvable terminal-email signal
And the configured `people` list has more than one registered person (multi-user mode)
When caller verification runs
Then the terminal-identity branch rejects the call as login-required-in-multi-user-mode
```

```
Given the same unresolved-email call, but the configured `people` list has zero or one registered person (single-user mode)
When caller verification runs
Then the terminal-identity branch returns a CallerIdentity with human_role=`admin` (Anonymous-admin fallback)
```

### Cross-context references

- Consumed by every protected operation in the identity context, either directly or transitively through the command-clearance capability.
- Reads from the `agent_runtime` bounded context (sessions, via the session loader) and from the `config` bounded context (the human-identity resolution capability for email→Role mapping).
- The session-token branch interlocks with session-token issuance — see `feature/identity/session-token-issuance` and `feature/identity/session-token-validation`. The derived system_role is the same value principal resolution would stamp on a token — see `feature/identity/principal-resolution`.
- In v2 this collapses into `identity.resolve(headers)` returning a typed `Principal` (or Anonymous); the v2 model unifies token-auth, session-id-auth, and email-trust under one resolution call.

## Known caveats

- The tmux cross-check is conditional. The dual-factor branch only rejects when BOTH the inbound tmux signal AND the stored session tmux name are present and differ. A call with no tmux signal (or a session record with no stored tmux name) passes the check silently. This is intentional — identity-context-spawned tasks without a tmux pane must still authenticate — but it weakens the dual-factor property for that subset of callers.
- The session and token resolution layers maintain short-lived caches. A freshly closed session can resolve briefly through the cache; cache invalidation is called on session close to mitigate, but a race window exists.
- The terminal-email fallback in single-user mode stamps `admin` even when no email is present. This is the v1 single-user convenience — it is explicitly NOT how v2 will behave (v2 returns Anonymous and lets the caller decide).
- System-role derivation falls back to the heuristic "if `working_slug` is set, treat as worker" when `system_role` is unset. A session record with a stale `working_slug` would mis-band as worker. The column-first ordering protects current deployments.
- The CLI deliberately suppresses token/session-id signals when the tmux session name is `tc_tui` (the trusted TUI). TUI callers ALWAYS go the terminal-email path even though they live in tmux.
