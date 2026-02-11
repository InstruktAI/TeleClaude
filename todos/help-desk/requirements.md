# Help Desk Platform — Requirements

## Goal

Establish `help-desk` as the universal entry point for external interactions, with
built-in identity resolution from adapter metadata. Known people (from config) get
full access. Unknown people get jailed in the help-desk lobby.

## Research Input (Required)

- `docs/third-party/claude-code/permissions.md` — CWD restriction and denial rules.
- `docs/third-party/gemini-cli/permissions.md` — Sandbox and directory mounting.
- `docs/third-party/codex-cli/permissions.md` — Profile-based autonomy.

## Core Requirements

### 1. Identity Resolution (from adapter metadata)

Sessions already carry `origin` and `channel_metadata` from adapters. The daemon
maps that metadata against people config to determine who the person is.

- **IdentityResolver** reads `GlobalConfig.people` + per-person creds from
  `~/.teleclaude/people/*/teleclaude.yml` at startup.
- Resolution by origin:
  - **telegram**: match `channel_metadata.user_id` against per-person `creds.telegram.user_id`.
  - **web**: match `channel_metadata.email` (from JWT, passed by web boundary).
  - **mcp child**: inherit parent session's identity via `initiator_session_id`.
  - **tui**: admin by default (local machine user).
  - **future adapters** (WhatsApp, Discord): same pattern — match platform user ID.
- Match found → known person with role from config. No match → unauthorized.
- **IdentityContext** dataclass: `person_name`, `person_email`, `person_role`,
  `platform`, `platform_user_id`. Nullable for unauthorized.

### 2. Roles

Two roles plus unauthorized:

- **admin**: full access to everything. TUI users. Configured people with `role: admin`.
- **member**: known person, broad access but no destructive ops (deploy, end others' sessions).
- **unauthorized**: not in config. Jailed to help-desk. No role in config needed — it's the default for unknowns.

### 3. Session Binding

- DB migration: add `human_email TEXT`, `human_role TEXT` to sessions table.
- Stamp identity during `create_session` from resolved `IdentityContext`.
- Child sessions inherit parent's identity.
- `SessionSummary` and DTO gain the identity fields.

### 4. Universal Ingress (The Lobby)

- **Forced Path:** Any session from an unauthorized person MUST be rooted in `help-desk`.
- **Invariant:** `create_session` overrides `project_path` to `help-desk` for unauthorized origins.

### 5. Dual-Profile Agent Launch

- **Admin/Member:** Launch with `profile="default"` (unrestricted). Can spawn child sessions in other projects.
- **Unauthorized:** Launch with `profile="restricted"` (jailed). Cannot spawn child sessions.
- Selection derived from resolved `IdentityContext`.

### 6. Agent Configuration

- Refactor `AGENT_PROTOCOL` to support named profiles:
  - `default`: `--dangerously-skip-permissions` (Claude), `--yolo` (Gemini).
  - `restricted`: `permissions.deny` (Claude), `--sandbox` (Gemini).

### 7. Filesystem Jailing

- **Claude:** `help-desk/.claude/settings.json` denies parent access (`../*`) and system paths.
- **Mounts:** Explicitly mount `~/.teleclaude/docs` for knowledge access via CLI flags.

### 8. Human Role Tool Gating

- Extend `role_tools.py` with human role filtering parallel to AI role filtering.
- `admin`: no restrictions.
- `member`: exclude deploy, remote session termination, agent availability mutation.
- `unauthorized`: read-only tools only (handled by restricted profile + help-desk jail).
- MCP wrapper reads `human_role` from session record (not a file on disk).

## Success Criteria

1. Telegram user_id maps to known person from config.
2. Unknown adapter user gets jailed to help-desk with restricted profile.
3. Admin in help-desk can spawn agent in other projects.
4. Unauthorized user cannot read `../config.yml`.
5. Unauthorized user CAN read `~/.teleclaude/docs/baseline.md`.
6. Sessions carry `human_email` and `human_role` in DB.
7. Child sessions inherit parent identity.
8. Human role tool filtering works alongside AI role filtering.

## Dependencies

- **config-schema-validation** — provides `PersonEntry`, `PersonConfig`, `load_global_config`.
