# Help Desk Platform — Implementation Plan

## Phase 1: Identity Resolver & Session Binding

Build the identity lookup and stamp it on sessions.

- [x] **Human role constants** in `teleclaude/constants.py`:
  - `HUMAN_ROLE_ADMIN = "admin"`, `HUMAN_ROLE_MEMBER = "member"`.
  - `HUMAN_ROLES = {"admin", "member"}`.

- [x] **IdentityContext + IdentityResolver** in `teleclaude/core/identity.py` (new):
  - `IdentityContext` dataclass: `person_name`, `person_email`, `person_role`,
    `platform`, `platform_user_id`. All nullable for unauthorized.
  - `IdentityResolver.__init__(people, person_configs)` builds lookup maps:
    `_by_email`, `_by_username`, `_by_telegram_user_id`.
  - `resolve(origin, channel_metadata) -> IdentityContext | None`:
    - telegram → match `user_id` against per-person creds.
    - web → match `email` from metadata.
    - tui → admin (local user).
    - mcp → returns None (caller handles parent inheritance).
    - no match → returns None (unauthorized).
  - `get_identity_resolver()` module function: calls `load_global_config()`,
    scans `~/.teleclaude/people/*/teleclaude.yml`, returns singleton.

- [x] **DB migration** in `teleclaude/core/migrations/`:

  ```sql
  ALTER TABLE sessions ADD COLUMN human_email TEXT;
  ALTER TABLE sessions ADD COLUMN human_role TEXT;
  ```

- [x] **Session model updates**:
  - `teleclaude/core/db_models.py`: add `human_email`, `human_role` optional fields.
  - `teleclaude/core/models.py`: add to `SessionSummary`.
  - `teleclaude/api_models.py`: add to `SessionSummaryDTO` + `from_core()`.

- [x] **Session creation binding** in `teleclaude/core/command_handlers.py`:
  - In `create_session`, call `get_identity_resolver().resolve(origin, channel_metadata)`.
  - Stamp `human_email`, `human_role` on session record.
  - For child sessions: inherit parent's identity via `initiator_session_id`.

- [x] **Unit tests** in `tests/unit/test_identity.py`:
  - Resolver maps telegram user_id to known person.
  - Resolver maps email to known person.
  - Unknown signals return None.
  - Session created with identity has fields set.
  - Child session inherits parent identity.

## Phase 2: Configuration Refactor (Dual Profiles)

- [x] **Update `teleclaude/constants.py`**:
  - `AGENT_PROTOCOL` structure: replace flat `flags` with `profiles` dict.
  - Define `default` and `restricted` for each agent.

- [x] **Update `teleclaude/config/__init__.py`**:
  - `AgentConfig` holds `profiles` dict instead of `flags` str.

- [x] **Update `teleclaude/core/agents.py`**:
  - `get_agent_command` accepts `profile: str = "default"`.
  - Looks up flags from `agent_config.profiles[profile]`.

## Phase 3: The Routing Logic (The Trap)

- [x] **Modify `create_session`** in `teleclaude/core/command_handlers.py`:
  - After identity resolution (Phase 1):
    - Admin/Member → proceed normally, `profile="default"`.
    - Unauthorized (None identity) → force `project_path` to help-desk,
      `profile="restricted"`. Log the redirect.
  - Pass selected `profile` to agent launch.

- [x] **Human role tool gating** in `teleclaude/mcp/role_tools.py`:
  - `HUMAN_ROLE_EXCLUDED_TOOLS` dict parallel to AI role filtering.
  - `admin`: no restrictions.
  - `member`: exclude deploy, end_session (others'), mark_agent_status.
  - MCP wrapper reads `human_role` from session DB record.

## Phase 4: Project Scaffolding

- [x] **Create `help-desk/`** directory in repo root.
- [x] **Claude security**: `help-desk/.claude/settings.json` with deny rules.
- [x] **Documentation**: `help-desk/README.md` visible to jailed agents.

## Phase 5: Verification

- [x] Unit test: `create_session` overrides path for unauthorized.
- [x] Unit test: identity resolver returns correct person for known telegram user.
- [x] Unit test: human role tool filtering blocks expected tools for member.
- [x] Manual: start session as "customer", verify jail works (covered by integration test assertions).

## Files Changed

| File                                  | Change                          |
| ------------------------------------- | ------------------------------- |
| `teleclaude/constants.py`             | Human role constants + profiles |
| `teleclaude/core/identity.py`         | New — resolver + context        |
| `teleclaude/core/migrations/`         | New migration                   |
| `teleclaude/core/db_models.py`        | Add identity columns            |
| `teleclaude/core/models.py`           | Add identity to SessionSummary  |
| `teleclaude/api_models.py`            | Add identity to DTO             |
| `teleclaude/core/command_handlers.py` | Resolve + stamp + trap          |
| `teleclaude/core/agents.py`           | Profile-based launch            |
| `teleclaude/config/__init__.py`       | Profile support                 |
| `teleclaude/mcp/role_tools.py`        | Human role filtering            |
| `help-desk/`                          | New project directory           |
| `tests/unit/test_identity.py`         | New tests                       |
