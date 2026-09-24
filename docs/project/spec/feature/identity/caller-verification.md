---
description: "Resolve every authenticated inbound call into a `CallerIdentity` via the identity context's single caller-verification capability."
visibility: 'public'
---

# Caller Verification — Spec

## Required reads

- @docs/project/spec/domain/identity.md
- @docs/project/spec/identity-and-auth.md

## What it is

<!-- planned-change:fix-history-role-filter-fails-open-on-unresolved-role -->
Caller verification is the identity context's single resolution capability: it turns the four caller-identity signals carried on every authenticated inbound call into a typed `CallerIdentity` value (the v1 ancestor of v2's `Principal`). Every authorized operation begins with the same precedence — a session-token check, then a dual-factor session-id + tmux cross-check, then a terminal-email lookup, with a final fallback that either returns an admin-role Anonymous (single-user mode) or rejects the caller as unauthenticated (multi-user mode). The capability answers "who is this caller and what bands do they carry?" before any business logic runs.
<!-- change:fix-history-role-filter-fails-open-on-unresolved-role -->
Caller verification is the identity context's single resolution capability: it turns the four caller-identity signals carried on every authenticated inbound call into a typed `CallerIdentity` value (the v1 ancestor of v2's `Principal`). Every authorized operation begins with the same precedence — a session-token check, then a dual-factor session-id + tmux cross-check, then a terminal-email lookup. A call that none of them resolves to a session or a registered person is rejected as unauthenticated, whatever the number of registered people. On a call that names a session, the session's own identity outranks the terminal-email signal. The capability answers "who is this caller and what bands do they carry?" before any business logic runs.
<!-- /planned-change:fix-history-role-filter-fails-open-on-unresolved-role -->

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

<!-- planned-change:fix-history-role-filter-fails-open-on-unresolved-role -->
```
Given the same unresolved-email call, but the configured `people` list has zero or one registered person (single-user mode)
When caller verification runs
Then the terminal-identity branch returns a CallerIdentity with human_role=`admin` (Anonymous-admin fallback)
```
<!-- change:fix-history-role-filter-fails-open-on-unresolved-role -->
#### UC-CV-TERMINAL-NO-PERSON: A call that names no person is refused on every host

```
Given a call with no session-token and no session id
And it carries no terminal-email signal, or one that matches no registered person
When caller verification runs
Then the terminal-identity branch rejects the call as login-required
And this holds whatever the number of registered people, including zero or one
And no role is granted to a call that names no person
```
<!-- /planned-change:fix-history-role-filter-fails-open-on-unresolved-role -->

<!-- planned:external-session-identity -->
#### UC-CV-ATTESTED-RESOLVES: An attested local caller resolves to the session that owns its process tree

```gherkin
Given a call over the local socket carrying no session-token and no caller-session-id
And the kernel identifies the connected peer process instance
And exactly one open session's root process instance occurs in that peer's verified ancestry
When caller verification runs
Then the attested branch resolves that session
And the returned CallerIdentity carries the session's existing principal and role
And the terminal-email branch is not taken
```

#### UC-CV-ATTESTED-UNPROVEN: An attested caller owning no session is refused, never degraded

```gherkin
Given a call over the local socket carrying no session-token and no caller-session-id
And no open session's root process instance occurs in the peer's verified ancestry
When caller verification runs on a session-scoped operation
Then the call is rejected as unauthenticated
And no machine-global last-login identity is returned in place of a session identity
```

#### UC-CV-ATTESTED-NESTED: A caller inside nested enrolled sessions resolves to the narrowest one

```gherkin
Given a call over the local socket whose peer ancestry contains the enrolled roots of two open sessions
And one of those roots is a descendant of the other
When caller verification runs
Then the attested branch resolves the session whose root is nearest the caller
And the enclosing session's identity is not returned for that caller
```

<!-- /planned:external-session-identity -->

#### UC-CV-DAEMON-SELF: The daemon's own calls resolve to its system principal, never to a person

```
Given a call carrying the daemon's process-local credential and no session-token or caller-session-id
When caller verification runs
Then the returned CallerIdentity carries the daemon's system principal and the system role
And it carries no email and no session id
And the terminal-email branch is not taken
```

#### UC-CV-DAEMON-FORGED: A daemon credential the daemon did not mint resolves nothing

```
Given a call from outside the daemon process carrying a daemon-credential value the daemon did not mint
When caller verification runs
Then the credential resolves no identity
And verification continues with the caller's remaining signals, rejecting the call when none of them resolve
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
Then the returned CallerIdentity carries principal="system:daemon"
And a gate that requires a human principal refuses the caller
```

#### UC-CV-SESSION-PRINCIPAL-NONE: A human_role-only session keeps no principal yet stays authorized on its role

```
Given a call with no session-token signal and a caller-session-id whose session record carries only a human_role — no inherited principal, no human_email, and no system_role
When caller verification runs
Then the returned CallerIdentity carries principal=None and retains the session's human_role as the authorization basis
And a gate that requires a human principal refuses the caller
```

<!-- planned:fix-history-role-filter-fails-open-on-unresolved-role -->
#### UC-CV-SESSION-OUTRANKS-TERMINAL: A session's own identity outranks a terminal-email signal

```
Given a call with no session-token signal and a caller-session-id whose session record carries an identity — a principal, or a person's email
And the call also carries a terminal-email signal
When caller verification runs
Then the returned CallerIdentity takes its email from the session record, never from the signal
And a human role the session record does not store is resolved for the session's own person
And a session carrying the platform's principal gains no email from the signal
And the terminal-email signal is consulted only for a session record that carries no identity at all
```
<!-- /planned:fix-history-role-filter-fails-open-on-unresolved-role -->

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
<!-- planned-change:fix-history-role-filter-fails-open-on-unresolved-role -->
- The terminal-email fallback in single-user mode stamps `admin` even when no email is present. This is the v1 single-user convenience — it is explicitly NOT how v2 will behave (v2 returns Anonymous and lets the caller decide).
<!-- change:fix-history-role-filter-fails-open-on-unresolved-role -->
- No host shape turns a call that names no person into an admin. The single-person convenience lives in the terminal reader, which answers a fresh terminal with the sole registered person's email (`feature/identity/terminal-email-login` UC-TEL5); a caller with no terminal sends no email and is refused here.
<!-- /planned-change:fix-history-role-filter-fails-open-on-unresolved-role -->
- System-role derivation falls back to the heuristic "if `working_slug` is set, treat as worker" when `system_role` is unset. A session record with a stale `working_slug` would mis-band as worker. The column-first ordering protects current deployments.
- The CLI deliberately suppresses token/session-id signals when the tmux session name is `tc_tui` (the trusted TUI). TUI callers ALWAYS go the terminal-email path even though they live in tmux.
