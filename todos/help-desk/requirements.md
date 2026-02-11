# Help Desk Platform — Requirements

## Goal

Route every external session to a **home folder** based on identity. Known people
land in their personal home. Unknown people land in `help-desk` (the lobby). Each
home is a durable project folder that accumulates memory and history for that person
or purpose over time.

Every person — admin, member, or stranger — gets a personal entry point. They DM the
bot, the bot recognizes them, and starts an agent in their home. That agent is their
personal assistant. It learns about them over time.

## Research Input (Required)

- `docs/third-party/claude-code/permissions.md` — CWD restriction and denial rules.
- `docs/third-party/gemini-cli/permissions.md` — Sandbox and directory mounting.
- `docs/third-party/codex-cli/permissions.md` — Profile-based autonomy.

## What Already Exists

- `IdentityResolver` + `IdentityContext` in `teleclaude/core/identity.py` — resolves
  by email and username. Singleton via `get_identity_resolver()`.
- `PersonEntry` schema (`name`, `email`, `username`, `role`) in `config/schema.py`.
  Role is `Literal["admin", "member", "contributor", "newcomer"]` with default `"member"`.
- `PersonConfig` with `creds.telegram.user_id: int` in per-person `teleclaude.yml`.
- `TelegramCreds` already has `user_name: str` and `user_id: int`.
- Telegram adapter has `user_whitelist` from `TELEGRAM_USER_IDS` env var.
- `channel_metadata` flows from adapters but currently only carries `message_id`.
- Telegram adapter is supergroup-only: text handler filters `ChatType.SUPERGROUP`,
  sessions are topics in the supergroup. DMs are completely ignored.
- Worktree `trees/person-identity-auth` exists (may contain prior work).

## Core Requirements

### 1. Home Folders

Every person gets a **home** — a project folder where their sessions live.

- **PersonEntry** gains a `home: Optional[str]` field (absolute path to their home folder).
- When `home` is None, sessions use the project_path from the command (no override).
- **`help-desk`** is the hardcoded home for unauthorized users. It is a folder in the
  repo root that ships with the project. Path derived from daemon working directory.
- Home folders are durable. Once assigned, they don't move.
- Each home accumulates agent memory and conversation history over time — the agent
  in that folder becomes a personal assistant that learns about its person.
- The `help-desk/` directory must exist before the daemon can route sessions to it.
  Created during build; absence at runtime is a startup validation error logged as warning.

### 2. Identity Resolution (extend existing)

Extend `IdentityResolver` to resolve from adapter metadata, not just email/username.

- **telegram**: adapters must pass `user_id` in `channel_metadata`. Resolver matches
  against `PersonConfig.creds.telegram.user_id`. Requires loading per-person configs
  from `~/.teleclaude/people/*/teleclaude.yml`.
- **web**: match `channel_metadata.email` (from JWT, passed by web boundary).
- **mcp child**: inherit parent session's identity via `initiator_session_id`.
- **tui**: admin by default (local machine user).
- **future adapters** (WhatsApp, Discord): same pattern — match platform user ID.
- Match found → known person with role and home from config.
- No match → unauthorized → home is `help-desk`.
- `IdentityContext` gains `home: Optional[str]` and `name: Optional[str]` fields.

### 3. Roles

The schema has four roles: `admin`, `member`, `contributor`, `newcomer`. For access
control, these map to three tiers:

- **admin**: full access. TUI users. Configured people with `role: admin`. Still gets
  routed to their home when coming from an external adapter.
- **trusted** (`member`, `contributor`): known person, broad access but no destructive ops.
- **unauthorized** (`newcomer` or not in config): jailed to `help-desk`. Default for unknowns.

The `newcomer` role is the explicit "known but untrusted" state — a person who exists
in config but hasn't been promoted yet. They get the same jail as unauthorized users.

### 4. Session Binding

- DB migration (008): add `human_email TEXT`, `human_role TEXT` to sessions table.
- Stamp identity during `create_session` from resolved `IdentityContext`.
- Child sessions inherit parent's identity.
- `SessionSummary` and DTO gain the identity fields.

### 5. Home Routing (The Trap)

- **Forced Path:** `create_session` resolves identity from origin + `channel_metadata`.
  - Known person with home → override `project_path` to their `home`.
  - Known person without home → no override (use command's project_path).
  - Unknown person → override `project_path` to `help-desk`.
  - TUI / MCP child → no override (current behavior preserved).
- **Invariant:** external adapter sessions from unknown users always land in help-desk.

### 6. Telegram DM as Personal Channel

Currently the telegram adapter only handles supergroup messages. This must change:

- **DM handler:** Add a handler for `filters.ChatType.PRIVATE` messages.
- **Flow:** User DMs the bot → adapter extracts `user_id` → passes it in
  `channel_metadata` → `create_session` resolves identity and routes to home.
- **Session lifecycle in DMs:** The DM chat itself is the channel. No forum topics.
  Messages from the agent go back to the same DM using `chat_id` (the user's private
  chat ID). One active session per DM user.
- **DM output routing:** `send_message` must detect DM sessions (no `message_thread_id`
  in adapter metadata) and send directly to `chat_id` instead of supergroup + topic.
  The DM uses the same single-persistent-message editing pattern as supergroup topics.
- **Session tracking:** Track active DM session per user (keyed by telegram `user_id`).
  Store `dm_chat_id` in session adapter metadata for reply routing.
- **Whitelist scoping:** The `user_whitelist` / `TELEGRAM_USER_IDS` env var remains
  only for supergroup access (admin control room). DMs bypass the whitelist — identity
  resolution handles authorization. Unknown DM users get routed to `help-desk`.
- **Supergroup unchanged:** The existing supergroup behavior stays for admins. The
  supergroup is the control room for managing sessions across projects.

### 7. Dual-Profile Agent Launch

- **Admin/Trusted:** Launch with `profile="default"` (unrestricted).
- **Unauthorized/Newcomer:** Launch with `profile="restricted"` (jailed).
- Selection derived from resolved `IdentityContext`.

### 8. Agent Configuration

- Refactor `AGENT_PROTOCOL` to support named profiles:
  - `default`: current `flags` value (`--dangerously-skip-permissions` for Claude, `--yolo` for Gemini).
  - `restricted`: safe flags per research specs.
- Backward compatibility: existing code that reads `AGENT_PROTOCOL[agent]["flags"]` must
  continue to work during migration. Use `profiles["default"]` as the canonical path and
  keep `flags` as a computed alias until all callsites are updated.

### 9. Filesystem Jailing (help-desk only)

- **Claude:** `help-desk/.claude/settings.json` denies parent access (`../*`) and system paths.
- **Mounts:** Explicitly mount `~/.teleclaude/docs` for knowledge access via CLI flags.
- Known people's home folders are NOT jailed — they get the default profile.

### 10. Human Role Tool Gating

- Extend MCP wrapper with human role filtering parallel to AI role filtering.
- `admin`: no restrictions.
- `trusted` (member/contributor): exclude deploy, remote session termination, agent availability mutation.
- `unauthorized`/`newcomer`: read-only tools only (handled by restricted profile + help-desk jail).
- MCP wrapper reads `human_role` from session record via DB lookup.

### 11. Documentation

This feature is the foundation for onboarding people. Documentation is a deliverable,
not an afterthought.

- **Operator guide** (`docs/project/procedure/onboarding-people.md`):
  - How to add a person to `GlobalConfig.people` (name, email, role, home).
  - How to set up their per-person `teleclaude.yml` with platform creds.
  - How to create their home folder and what goes in it.
  - How to verify the setup works (DM the bot, check session lands in home).
- **Person quickstart** (`help-desk/README.md` or similar):
  - What the person sees: "DM the bot on Telegram, it knows who you are."
  - What their personal assistant can do.
  - How to get help if something goes wrong.
- **Architecture doc** (`docs/project/design/home-routing.md`):
  - How identity resolution works end-to-end.
  - The routing decision tree (origin → identity → home → profile).
  - How jailing works for unauthorized users.
  - How the Telegram DM channel maps to sessions.

## Success Criteria

1. Telegram `user_id` maps to known person from config → session lands in their home.
2. Unknown adapter user → session lands in `help-desk` with restricted profile.
3. Admin coming from Telegram DM → session lands in admin's home (not help-desk).
4. Unauthorized user cannot read `../config.yml` from help-desk.
5. Unauthorized user CAN read `~/.teleclaude/docs/baseline.md`.
6. Sessions carry `human_email` and `human_role` in DB.
7. Child sessions inherit parent identity.
8. Human role tool filtering works alongside AI role filtering.
9. Home folders persist and accumulate history across sessions.
10. A person can DM the Telegram bot and get a session in their home — no supergroup needed.
11. Operator guide exists and covers end-to-end person onboarding.
12. Architecture doc captures the routing design for future adapter implementors.
13. Known person with `home=None` → session uses the command's project_path (no override).
14. `newcomer` role person → jailed to help-desk same as unauthorized.

## Dependencies

- None (config-schema-validation already delivered; `PersonEntry`, `PersonConfig`,
  `load_global_config` all exist).
