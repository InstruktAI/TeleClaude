---
id: 'project/spec/identity-and-auth'
type: 'spec'
scope: 'project'
description: 'Authoritative surface for system-wide identity, authentication, and person management.'
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

Daemon-spawned agent sessions use a token-based credential instead of the
terminal-email or dual-factor session-id path.

**Flow:**
1. Daemon calls `resolve_session_principal(session)` at bootstrap to derive a principal:
   - `human:<email>` when `session.human_email` is set.
   - `system:<session_id>` for daemon-spawned (automated) sessions.
   - Inherited `session.principal` is reused directly for child sessions so the full
     agent chain shares one stable identity.
2. Daemon issues a token: `db.issue_session_token(session_id, principal, role)` → UUID.
3. Token is injected into the tmux environment as `TELEC_SESSION_TOKEN`.
4. CLI calls from within the session send `x-session-token: <token>` header.
5. `verify_caller()` validates the token first (before the session-id dual-factor path):
   - Calls `db.validate_session_token(token)` (checks expiry and revoked_at).
   - Populates `CallerIdentity.principal` and `CallerIdentity.principal_role` from the record.
6. `is_command_allowed()` uses `principal_role` as the effective human role when `human_role`
   is absent — this lets daemon-spawned sessions pass role clearance without a human behind them.
7. On session close, `db.revoke_session_tokens(session_id)` is called and the token cache is
   invalidated so in-flight requests with the stale token are rejected immediately.

**Key headers:**
- `x-session-token`: daemon-issued credential (takes priority over `x-caller-session-id`).

**`telec auth whoami` inside an agent session:**
When `TELEC_SESSION_TOKEN` is present, `whoami` resolves the principal via the daemon's
`GET /auth/whoami` endpoint and prints `Principal: <principal>` and `Role: <role>`.
Falls back to terminal email display when no token is present.

**Principal types:**
| Format | When set |
|---|---|
| `human:<email>` | Session created with a human identity (human_email set) |
| `system:<session_id>` | Daemon-spawned automated session |

**Token ledger table:** `session_tokens` — stores token, session_id, principal, role,
issued_at, expires_at, revoked_at. Tokens expire after 24 h and are revoked on session close.

### 4) Web authentication (NextAuth)

The Web Interface uses **NextAuth (v5 Beta)** with the following flow:

1. **Selection:** User selects their name from `/api/people` (which reads from YAML).
2. **OTP Delivery:** A 6-digit verification code is sent via `nodemailer` using the `SMTP_*` and `EMAIL_FROM` environment variables.
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

Child worker sessions must be linked to parent orchestrator session identity.

- `/sessions/run` requires non-empty caller session identity.
- When present, `initiator_session_id` is written into channel metadata for child-session linkage.
- Requests without caller session identity are rejected instead of creating unlinked children.

## Known caveats

- Headless/native hook identity follows `session-identity-truth`; it is distinct from terminal login.
- TUI login bridge is read-only runtime context, not a replacement for `telec auth login`.
