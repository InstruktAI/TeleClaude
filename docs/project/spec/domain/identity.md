---
id: project/spec/domain/identity
type: spec
domain: software-development
scope: project
visibility: public
status: target
delivered_by:
  - v2-identity-cutover
description: Identity bounded context — principals (people, machines, sessions), tokens,
  and the resolution of any caller into an authenticated Principal. Foundation for
  every authorization decision.
---

# Identity Domain Spec — Spec

## Required reads

- docs/global/software-development/principle/domain-driven-design.md
- docs/global/software-development/spec/domain-spec.md
- @docs/project/spec/domain/glossary.md
- @docs/project/spec/domain/context-map.md
- @docs/project/design/architecture-v2/auth-model.md

## What it is

The `identity` bounded context owns who is making any given call into the platform. It models people, machine processes, and agent sessions as `Principal` values; issues and validates the credentials that prove a caller's identity; and exposes a single resolution function that turns raw transport inputs (env vars, HTTP headers, tokens) into a typed `Principal` for downstream authorization.

This context does NOT own: session lifecycle (`agent_runtime`), workflow state (`workflow`), authorization policies that are domain-specific (each domain enforces its own rules against the resolved `Principal`).

## Canonical fields

### Ubiquitous language

**Principal**
: The authenticated caller of an operation. Three subtypes: `HumanPrincipal`, `MachinePrincipal`, `SessionPrincipal`. Every authorized operation begins with a `Principal` resolved from the transport.

**Human principal**
: A person, identified by email + role. Email is the durable identifier. Role determines what they're allowed to do.

**Machine principal**
: A daemon, worker, or other long-running process, identified by an API token issued at install time.

**Session principal**
: An agent session, identified by its session_id (from `agent_runtime`) and credentialed by a session token. Lives only for the duration of a session.

**API token** (per glossary)
: Long-lived credential for a machine principal. Carried in `Authorization` header or env var. Issued once at install / wizard time; revocable.

**Session token** (per glossary)
: Credential bound to a specific `session_id`. Carried in `x-session-token` header. Issued when a session starts; expires when the session ends.

**Role**
: Categorical authorization band. The canonical roles are `admin`, `subscriber`, `anonymous`. Roles are enums in the Rust model; new roles require a schema migration.

**Resolution**
: The act of turning a raw caller into a `Principal`. Input: any combination of `x-session-token`, `x-caller-session-id`, `x-tmux-session`, `x-telec-email` headers (HTTP), `TELECLAUDE_*` env vars (subprocess), or local config (CLI). Output: exactly one `Principal` (or `Anonymous`).

**Anonymous**
: The principal returned when no credentials resolve. Has the `anonymous` role; authorized only for public surfaces.

### Aggregates

#### Principal (aggregate)

- **Root:** `Principal` (sum type / Rust enum)
- **Contains:** for `HumanPrincipal`: `email`, `name`, `role`. For `MachinePrincipal`: `machine_id`, `host`, `role`. For `SessionPrincipal`: `session_id`, `tmux_session_name`, `agent`, `binding_email` (the human who started this session), `role` (inherited from binding).
- **Invariants:**
  - Every `HumanPrincipal` has a unique email.
  - Every `MachinePrincipal` has a unique `(machine_id, host)` tuple.
  - Every `SessionPrincipal` references an existing `session_id` in `agent_runtime` (cross-context invariant; broken by the eventual deletion of the session in agent_runtime, but identity's record of the binding survives until token revocation).
  - A principal's role is set at creation. Role changes require explicit revocation + reissue of credentials.
  - `Anonymous` carries no other fields; it is a degenerate root.
- **Identifier:** email (humans), `(machine_id, host)` (machines), `session_id` (sessions).
- **Lifecycle:** Humans are created via the config wizard (people list); deletion is rare and requires explicit operator action. Machines are created at install time. Sessions are created by `agent_runtime` and a `SessionPrincipal` is materialized by identity when a session token is issued.

#### Token (aggregate)

- **Root:** `Token`
- **Contains:** `token_kind` (`api` | `session`), opaque secret (stored as hash), `issued_to` (principal identifier), `issued_at`, `revoked_at` (nullable).
- **Invariants:**
  - A token's secret is stored as a cryptographic hash; the plaintext exists only at issuance time and is returned to the caller exactly once.
  - A revoked token (`revoked_at` is non-null) MUST fail resolution.
  - Session tokens automatically revoke when the bound session ends (via `agent_runtime.session.ended` event subscription, eventually consistent).
  - API tokens have no automatic expiry; revocation is explicit.
- **Identifier:** the secret's hash (the storage key); the plaintext is the wire form.
- **Lifecycle:** Issued by `identity.token.issue(...)`. Revoked by `identity.token.revoke(...)` or by session end. Hashed secrets persist forever for audit; revoked tokens cannot be reissued.

### Domain events emitted

#### `identity.principal.created`

- **Producer:** `identity`
- **Emitted when:** a new principal is added to the model (human added via config wizard, machine registered at install, session principal materialized on first token issuance).
- **Payload:** `principal_kind`, `principal_id`, `role`, `created_at`.
- **Visibility:** CLUSTER
- **Known consumers:** `integration` (subscription resolution for new humans), `workflow` (operator visibility audit), future audit log consumers.
- **Idempotency key:** `(principal_kind, principal_id)`.
- **Posture:** `commit-then-emit`.

#### `identity.token.issued`

- **Producer:** `identity`
- **Emitted when:** a token (API or session) is successfully issued.
- **Payload:** `token_kind`, `issued_to`, `issued_at`, `token_hash` (NEVER the plaintext).
- **Visibility:** CLUSTER
- **Known consumers:** audit log consumers; `agent_runtime` for session tokens (correlates the issuance with the session record).
- **Idempotency key:** `token_hash`.
- **Posture:** `commit-then-emit`.

#### `identity.token.revoked`

- **Producer:** `identity`
- **Emitted when:** a token is revoked (explicit revocation, session end, or operator action).
- **Payload:** `token_kind`, `issued_to`, `token_hash`, `revoked_at`, `revoke_reason` (`explicit` | `session_ended` | `expired` | `operator`).
- **Visibility:** CLUSTER
- **Known consumers:** any service caching resolution results MUST invalidate on revocation; `agent_runtime` (cleanup on revocation cascade).
- **Idempotency key:** `(token_hash, revoked_at)`.
- **Posture:** `commit-then-emit`.

### Domain events consumed

#### `agent_runtime.session.ended`

- **Producer:** `agent_runtime`
- **Reaction:** auto-revoke the session token associated with the ended session (emits `identity.token.revoked` with reason `session_ended`).
- **Failure handling:** revocation failures are retried; the orphan token stays valid until reconciliation succeeds. Periodic reconciliation job catches drift.

### Use cases

#### v1 inventory (parity reference)

The bullets below index the v1 feature spec snippets that pin the behavior v2 must satisfy. Each entry describes what v1 actually does today — NOT what v2 provides (v2 is `status: target` at the spec level until cutover lands). Use these as the parity contract for `v2-identity-cutover`.

- v1 inventory: [principal resolution](../feature/identity/principal-resolution.md) — derive the canonical `(principal, role)` pair for a session via inherited → human → system precedence.
- v1 inventory: [session token issuance](../feature/identity/session-token-issuance.md) — issue a UUID4 session token for `system:*` principals at bootstrap; persist hash, return plaintext once.
- v1 inventory: [session token validation](../feature/identity/session-token-validation.md) — resolve `x-session-token` to a `CallerIdentity` via the ledger plus a TTL cache and defense-in-depth lifecycle check.
- v1 inventory: [session token revocation](../feature/identity/session-token-revocation.md) — delete a session's tokens at termination, invalidate auth caches, best-effort with cache safety nets.
- v1 inventory: [orphan session token cleanup](../feature/identity/orphan-session-token-cleanup.md) — periodic maintenance sweep deleting tokens whose owning session is closed or missing.
- v1 inventory: [caller verification](../feature/identity/caller-verification.md) — single FastAPI dependency resolving every request to a `CallerIdentity` via token → dual-factor session-id → terminal email precedence.
- v1 inventory: [command clearance](../feature/identity/command-clearance.md) — per-CLI-command role allowlist enforced server-side via `require_clearance` and `CommandAuth`.
- v1 inventory: [terminal email login](../feature/identity/terminal-email-login.md) — per-TTY auth file (with global fallback) recording the logged-in email for `x-telec-email` injection.
- v1 inventory: [whoami resolution](../feature/identity/whoami-resolution.md) — `telec auth whoami` and `GET /auth/whoami` echo the resolved principal/role for the caller.
- v1 inventory: [session identity file](../feature/identity/session-identity-file.md) — per-session `$TMPDIR/teleclaude_identity.json` carrying session_id, session_token, system_role, human_role.
- v1 inventory: [identity header trust boundary](../feature/identity/identity-header-trust-boundary.md) — middleware rejects `x-web-user-*` headers from non-trusted hosts (loopback/socket only).
- v1 inventory: [session access visibility](../feature/identity/session-access-visibility.md) — owner / `member`-with-shared / admin gating for web-frontend session-scoped API routes.
- v1 inventory: [human identity resolution](../feature/identity/human-identity-resolution.md) — singleton `IdentityResolver` mapping email / Telegram / Discord / WhatsApp signals to `PersonEntry` from the `people` config.
- v1 inventory: [TUI multi-user login gate](../feature/identity/tui-multi-user-login-gate.md) — `telec` startup refuses to launch the TUI without prior `telec auth login` when the config has multiple registered people.
- v1 inventory: [self restart authorization bypass](../feature/identity/self-restart-authorization-bypass.md) — any session may restart itself via `POST /sessions/{id}/agent-restart` with `self_restart: true`, bypassing the normal role check.

#### UC-IDN-1: Resolve caller from HTTP request

```
Given an HTTP request arrives at a v2 service endpoint
And the request carries headers x-session-token, x-caller-session-id, x-tmux-session, or x-telec-email (any combination)
When the service calls identity.resolve(headers)
Then identity returns exactly one Principal (or Anonymous)
And resolution follows precedence: session-token → API-token → email-trust → anonymous
And invalid or revoked tokens return Anonymous (not an error — the caller decides)
```

#### UC-IDN-2: Issue a session token at session start

```
Given agent_runtime is creating a new session
When agent_runtime calls identity.issue_session_token(session_id, binding_email)
Then identity creates a SessionPrincipal bound to (session_id, binding_email)
And issues a fresh session token, returning the plaintext exactly once
And persists the token hash with issued_at timestamp
And emits identity.token.issued
And agent_runtime stores the plaintext token on the session record for adapter consumption
```

#### UC-IDN-3: Auto-revoke on session end

```
Given agent_runtime emits agent_runtime.session.ended for session_id S
When identity's subscriber processes the event
Then identity looks up the SessionPrincipal for S
And revokes the bound session token (sets revoked_at)
And emits identity.token.revoked with reason session_ended
And any cached resolution that referenced this token becomes invalid on next check
```

#### UC-IDN-4: Add a person via config wizard

```
Given the TUI config wizard's people view
And the operator fills in name, email, role for a new person
When the operator confirms
Then the wizard calls identity.add_human(email, name, role)
And identity validates the email is unique
And creates a HumanPrincipal
And emits identity.principal.created
And the person can now resolve via x-telec-email header
```

#### UC-IDN-5: Operator revokes an API token

```
Given an operator decides to retire a machine principal's API token
When the operator runs `telec auth revoke --token-hash <hash>`
Then identity sets revoked_at on the token row
And emits identity.token.revoked with reason operator
And subsequent resolutions with that token return Anonymous
```

#### UC-IDN-6: Authorize an admin-only operation

```
Given a service handler receives a request
And calls identity.resolve(headers) which returns a Principal
When the handler's authorization check runs `principal.role == admin`
Then admin-role principals pass the check
And non-admin principals are rejected with a 403 / equivalent
And the handler logs the principal_id of the failed call (per security awareness)
```

### Context map position

- **Spine context** — every domain context depends on identity for principal resolution. No upstream contexts.
- **Customer-Supplier upstream to: `workflow`, `knowledge`, `agent_runtime`, `integration`, `agent_artifacts`** (and to `telec-api` and `telec-tui` binaries). Identity owns the resolution contract; consumers conform.
- **Subscribes to: `agent_runtime.session.ended`** for auto-revoke. The only event identity consumes.
- **Anti-corruption layer with v1 (during migration)** — v1 `teleclaude/core/db/_tokens.py` and `_sessions.py` use a slightly different shape (Pydantic models, different column names). The v2 ACL at `crates/identity/src/v1_compat.rs` (planned) converts. Disappears at `v2-identity-cutover`.

## Allowed values

- `principal_kind`: `human`, `machine`, `session`, `anonymous`.
- `role`: `admin`, `subscriber`, `anonymous`.
- `token_kind`: `api`, `session`.
- `revoke_reason`: `explicit`, `session_ended`, `expired`, `operator`.

## Known caveats

- Email-trust (`x-telec-email` header without a token) is a development convenience that MUST be disabled in production / public deployments. The header is honored only when the daemon is bound to localhost or running under explicit dev configuration. v2 hardens this with a config-driven gate.
- The role enum is fixed in the v2 model. Adding a new role is a schema migration, not a runtime configuration. This is deliberate — roles are authorization primitives, not user-tweakable settings.
- Per-service role definitions (e.g., "who can dispatch workers") are NOT identity's concern. Identity returns a `Principal` with a base role; each service maps its own operations to required roles.
- Session principals can outlive their sessions if revocation lags. Reconciliation jobs catch drift; consumers MUST handle the case where a session token resolves to a `SessionPrincipal` whose session_id no longer exists in `agent_runtime` (treat as Anonymous).
- Per-person config files (`~/.teleclaude/people/<name>/teleclaude.yml`) are owned by `config`, not identity. Identity reads the people list from the effective configuration to know which humans exist; the YAML authoring is config's job.
