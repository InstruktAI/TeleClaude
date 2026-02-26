---
id: 'project/spec/identity-and-auth'
type: 'spec'
scope: 'project'
description: 'Authoritative surface for system-wide identity, authentication, and person management.'
---

# Identity and Auth — Spec

## Required reads

- @project/spec/teleclaude-config
- @project/spec/command-surface
- @project/spec/session-identity-truth

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

### 3) Web authentication (NextAuth)

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
