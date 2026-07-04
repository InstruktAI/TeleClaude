---
description: 'Authoritative surface for system-wide identity, authentication, and person management.'
visibility: 'public'
---

# Identity and Auth — Spec

## Required reads

- @docs/project/spec/teleclaude-config.md
- @docs/project/spec/command-surface.md
- @docs/project/spec/session-identity-truth.md

## What it is

TeleClaude uses one identity model across API, TUI, web, and adapters:

- person identity comes from global `people` config,
- session identity comes from daemon-owned session records,
- authorization is enforced server-side on every protected route.

## Canonical fields

### 1) Person source of truth

| Field   | Type   | Description                                           |
| ------- | ------ | ----------------------------------------------------- |
| `name`  | string | Display name used in UI and logs.                     |
| `email` | string | Canonical email address used for OTP authentication.  |
| `role`  | enum   | One of: `admin`, `member`, `contributor`, `newcomer`. |

People are defined in global `~/.teleclaude/teleclaude.yml` under `people`.

### 2) Runtime identity headers

Protected local API routes use these headers:

- `x-caller-session-id`: TeleClaude session identity (daemon-owned, for lineage and role derivation).
- `x-tmux-session`: tmux server session name for cross-check.
- `x-telec-email`: terminal login identity (`telec auth login`) for non-session callers.

### 3) Agent session token auth

Token-based auth exists exclusively for daemon-spawned agent sessions — sessions
that have no human behind them and therefore cannot authenticate via terminal email
or the dual-factor session-id path.

**Human-initiated sessions never receive a token.** They authenticate via
`x-telec-email` (terminal login) or `x-caller-session-id` (dual-factor tmux
cross-check). The daemon does not issue a token for sessions with a `human:<email>`
principal.

**Who gets a token:**

| Principal type                | Token issued?                  | Auth path                                                   |
| ----------------------------- | ------------------------------ | ----------------------------------------------------------- |
| `human:<email>`               | **No**                         | `x-telec-email` or `x-caller-session-id` + tmux cross-check |
| `system:<session_id>`         | **Yes**                        | `x-session-token` header                                    |
| Inherited `session.principal` | **Yes** (if system-originated) | Inherits parent's auth path                                 |

**Token lifecycle:**

Each token is bound to exactly one `session_id`. It cannot be used to
authenticate as a different session. Tokens have no time-based expiry. A token
lives exactly as long as its session. The only event that invalidates a token
is session close, which calls `db.revoke_session_tokens(session_id)`. There is
no TTL, no timeout, no background sweep. Session close is the single lifecycle
boundary.

**Flow (system-principal sessions only):**

1. Daemon calls `resolve_session_principal(session)` at bootstrap to derive a principal:
   - `human:<email>` when `session.human_email` is set → **no token issued**.
   - `system:<session_id>` for daemon-spawned (automated) sessions → **token issued**.
   - Inherited `session.principal` is reused directly for child sessions so the full
     agent chain shares one stable identity.
2. For system principals only: daemon issues a token via
   `db.issue_session_token(session_id, principal, role)` → UUID.
3. Token is injected into the tmux environment as `TELEC_SESSION_TOKEN`.
4. CLI calls from within the session send `x-session-token: <token>` header.
5. `verify_caller()` validates the token first (before the session-id dual-factor path):
   - Calls `db.validate_session_token(token)` — checks `revoked_at` only.
   - Populates `CallerIdentity.principal` and `CallerIdentity.principal_role` from the record.
6. `is_command_allowed()` uses `principal_role` as the effective human role when `human_role`
   is absent — this lets daemon-spawned sessions pass role clearance without a human behind them.
7. On session close, `db.revoke_session_tokens(session_id)` is called and the token cache is
   invalidated so in-flight requests with the stale token are rejected immediately.

**Key headers:**

- `x-session-token`: daemon-issued credential for system sessions only
  (takes priority over `x-caller-session-id` when present).

**`telec auth whoami` inside an agent session:**
When `TELEC_SESSION_TOKEN` is present, `whoami` resolves the principal via the daemon's
`GET /auth/whoami` endpoint and prints `Principal: <principal>` and `Role: <role>`.
Falls back to terminal email display when no token is present (human sessions).

**Principal types:**

| Format                | When set                                                | Token? |
| --------------------- | ------------------------------------------------------- | ------ |
| `human:<email>`       | Session created with a human identity (human_email set) | No     |
| `system:<session_id>` | Daemon-spawned automated session                        | Yes    |

**Token ledger table:** `session_tokens` — stores token, session_id, principal, role,
issued_at, revoked_at. Token lifetime is controlled exclusively by revocation on
session close.

### 4) Web authentication (NextAuth)

The Web Interface uses **NextAuth (v5 Beta)** with the following flow:

1. **Email entry:** User enters their email address in the login form.
2. **OTP Delivery:** A 6-digit verification code is sent via `nodemailer` using the `SMTP_*` and `EMAIL_FROM` environment variables in production. In development (`NODE_ENV=development`), the code is logged to server output instead of being emailed.
3. **Verification:** `NextAuth` verifies the code.
4. **Authorization:** The `signIn` callback ensures the email matches a `people` entry in `teleclaude.yml`.

### 4) Terminal + TUI authentication

- `telec auth login <email>` writes a TTY-scoped login file.
- `telec auth login` is blocked inside generic tmux contexts.
- `telec` startup bridges outer-terminal login into trusted `tc_tui` via environment (`TELEC_AUTH_EMAIL`).
- Inside tmux, login identity is accepted only for trusted TUI context (`TELEC_TUI_SESSION=1` and tmux session `tc_tui`).

### 5) Multi-user enforcement

- If `people` contains more than one registered person:
  - TUI launch requires prior `telec auth login`,
  - daemon rejects tmux callers that have no `x-caller-session-id` and no resolvable `x-telec-email`.
- If `people` has zero/one person, legacy fallback role is still allowed for tmux callers without session identity.

### 6) Server-side authorization

Role clearance is daemon-side only (`verify_caller` + `require_clearance`):

- no client-side role claim is trusted,
- unknown/missing identity returns 401,
- insufficient role returns 403.

### 7) Session lineage invariant (child sessions)

Child worker sessions should be linked to parent orchestrator session identity when a caller session exists.

- `/sessions/run` accepts terminal/TUI callers whose identity is resolved by `verify_caller` even when `x-caller-session-id` is empty.
- When a caller session identity is present, `initiator_session_id` is written for child-session linkage.
- Requests without caller session identity remain valid, but they create unlinked sessions because terminal/TUI callers do not have a parent TeleClaude session.
- A lifecycle session the runner auto-dispatches for a todo whose `created_by_principal` is a `human:<email>` establishes that human as its root identity: the session row carries the owning human's `principal`/`human_email`, so its resolved principal is `human:<email>` rather than `system:<session_id>`, and the rest of the chain inherits it through `initiator_session_id`. The session's `system_role` is left untouched, so the attribution does not change what the session is authorized to do.

## Known caveats

- Headless/native hook identity follows `session-identity-truth`; it is distinct from terminal login.
- TUI login bridge is read-only runtime context, not a replacement for `telec auth login`.
