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
And the returned CallerIdentity carries the principal and principal_role resolved from the session record through the principal-resolution capability
```

```
Given the same call with tmux-session signal `tc_tui` while the stored tmux_session_name is `worker-8a2c1f4d`
When caller verification runs
Then the dual-factor branch rejects the call as a session-identity mismatch
```

```
Given a managed descendant inherits a caller-session-id or session-token from its session identity file
And the descendant has no TMUX environment membership
When a CLI client assembles caller identity signals
Then it sends the inherited session-token when present
And otherwise sends the inherited caller-session-id
And it omits the tmux-session signal without querying ambient tmux server state
And caller verification uses the token path or the intentional pane-less session-id path
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

#### UC-CV-SESSION-PRINCIPAL-HUMAN: A human-rooted session resolves to a human principal and clears the human gate

```
Given a call with no session-token signal and a caller-session-id whose session record has human_email set and no inherited principal
When caller verification runs
Then the dual-factor branch resolves the session through the principal-resolution capability
And the returned CallerIdentity carries principal="human:<email>" and the session's human_role
And a gate that requires a human principal accepts the caller
```

#### UC-CV-SESSION-PRINCIPAL-SYSTEM: A system-role session resolves to a system principal and the human gate refuses it

```
Given a call with no session-token signal and a caller-session-id whose session record has system_role set, no human_email, and no inherited principal
When caller verification runs
Then the returned CallerIdentity carries principal="system:<session_id>"
And a gate that requires a human principal refuses the caller
```

#### UC-CV-SESSION-PRINCIPAL-NONE: A human_role-only session keeps no principal yet stays authorized on its role

```
Given a call with no session-token signal and a caller-session-id whose session record carries only a human_role — no inherited principal, no human_email, and no system_role
When caller verification runs
Then the returned CallerIdentity carries principal=None and retains the session's human_role as the authorization basis
And a gate that requires a human principal refuses the caller
```

### Cross-context references

- Consumed by every protected operation in the identity context, either directly or transitively through the command-clearance capability.
- Reads from the `agent_runtime` bounded context (sessions, via the session loader) and from the `config` bounded context (the human-identity resolution capability for email→Role mapping).
- The session-token branch interlocks with session-token issuance — see `feature/identity/session-token-issuance` and `feature/identity/session-token-validation`. The derived system_role is the same value principal resolution would stamp on a token — see `feature/identity/principal-resolution`.
- In v2 this collapses into `identity.resolve(headers)` returning a typed `Principal` (or Anonymous); the v2 model unifies token-auth, session-id-auth, and email-trust under one resolution call.

## Known caveats

- The tmux cross-check is conditional. The dual-factor branch only rejects when BOTH the inbound tmux signal AND the stored session tmux name are present and differ. A call with no tmux signal (or a session record with no stored tmux name) passes the check silently. This is intentional — identity-context-spawned tasks without a tmux pane must still authenticate — but it weakens the dual-factor property for that subset of callers.

- CLI clients treat `TMUX` environment membership as the prerequisite for
  querying the current tmux session name. A successful ambient
  `tmux display-message` result without that membership is foreign server state,
  not caller identity, and is omitted.

- The session and token resolution layers maintain short-lived caches. A freshly closed session can resolve briefly through the cache; cache invalidation is called on session close to mitigate, but a race window exists.
- The terminal-email fallback in single-user mode stamps `admin` even when no email is present. This is the v1 single-user convenience — it is explicitly NOT how v2 will behave (v2 returns Anonymous and lets the caller decide).
- System-role derivation falls back to the heuristic "if `working_slug` is set, treat as worker" when `system_role` is unset. A session record with a stale `working_slug` would mis-band as worker. The column-first ordering protects current deployments.
- The CLI deliberately suppresses token/session-id signals when the tmux session name is `tc_tui` (the trusted TUI). TUI callers ALWAYS go the terminal-email path even though they live in tmux.
