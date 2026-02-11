# Help Desk Platform — Implementation Plan

## Phase 1: Home Field + Identity Extension

Add the `home` concept and extend identity resolution for adapter metadata.

- [ ] **Add `home` to `PersonEntry`** in `teleclaude/config/schema.py`:
  - `home: Optional[str] = None` — absolute path to this person's home folder.
  - Optional field (None means no home override; sessions use command's project_path).

- [ ] **Extend `IdentityContext`** in `teleclaude/core/identity.py`:
  - Add `home: Optional[str] = None` field.
  - Add `name: Optional[str] = None` field.

- [ ] **Extend `IdentityResolver`** in `teleclaude/core/identity.py`:
  - Load per-person configs (`~/.teleclaude/people/*/teleclaude.yml`) via
    `load_person_config(username)` from `teleclaude/config/loader.py`.
  - Build `_by_telegram_user_id: dict[int, PersonEntry]` map from
    `PersonConfig.creds.telegram.user_id` (keyed by person username → PersonConfig lookup).
  - Add `resolve(origin: str, channel_metadata: dict) -> IdentityContext | None`:
    - `origin="telegram"` → extract `user_id` from `channel_metadata`, match against
      `_by_telegram_user_id`. Return IdentityContext with home from PersonEntry.
    - `origin="web"` → extract `email` from `channel_metadata`, match via existing
      `_by_email`.
    - `origin="tui"` → return admin identity (local user).
    - `origin="mcp"` → return None (caller handles parent inheritance).
    - No match → return None (unauthorized).
  - Keep existing `resolve_by_email`/`resolve_by_username` for backward compatibility.

- [ ] **Pass `user_id` in telegram `channel_metadata`**:
  - In `InputHandlersMixin`, `CommandHandlersMixin`, `CallbackHandlersMixin`:
    add `metadata.channel_metadata["user_id"] = update.effective_user.id` alongside
    existing `message_id`.

## Phase 2: Session Binding

Stamp identity on sessions in the database.

- [ ] **DB migration 008** in `teleclaude/core/migrations/`:
  - File: `008_add_human_identity.py`
  - Follow existing pattern (async `up`/`down`, raw SQL, `PRAGMA table_info` check).

  ```sql
  ALTER TABLE sessions ADD COLUMN human_email TEXT;
  ALTER TABLE sessions ADD COLUMN human_role TEXT;
  ```

- [ ] **Session model updates**:
  - `teleclaude/core/db_models.py`: add `human_email: str | None`, `human_role: str | None`
    optional fields to Session model.
  - `teleclaude/core/models.py`: add to `SessionSummary` + `to_dict()` + `from_session()` +
    `from_dict()`.
  - `teleclaude/api_models.py`: add to `SessionSummaryDTO` + `from_core()`.

- [ ] **Session creation binding** in `teleclaude/core/command_handlers.py`:
  - In `create_session`, after getting `origin` and `channel_metadata`:
    call `get_identity_resolver().resolve(origin, channel_metadata)`.
  - Stamp `human_email`, `human_role` on session record.
  - For child sessions (`initiator_session_id` set): inherit parent's identity fields
    from DB lookup of parent session.

## Phase 3: Telegram DM as Personal Channel

Add DM handling alongside the existing supergroup behavior.

- [ ] **DM text handler** in `teleclaude/adapters/telegram_adapter.py`:
  - Register a new `MessageHandler` with `filters.ChatType.PRIVATE & filters.TEXT`.
  - Handler: `_handle_dm_message(update, context)`.
  - Registration must happen alongside existing supergroup handlers (not replace them).

- [ ] **DM handler logic** in `teleclaude/adapters/telegram/input_handlers.py`:
  - `_handle_dm_message(update, context)`:
    - Extract `user_id` from `update.effective_user.id`.
    - Extract `chat_id` from `update.effective_chat.id` (the DM chat).
    - Look up active session for this DM user (query sessions by adapter metadata
      `dm_user_id` field + lifecycle_status active).
    - If no active session: create one via `create_session` with `origin="telegram"`,
      `channel_metadata={"user_id": user_id, "dm_chat_id": chat_id}`.
      Identity resolution + home routing happens inside `create_session` (Phase 4).
    - If active session exists: forward message to it via `send_message` command.
    - No whitelist check for DMs — identity resolver handles authorization.

- [ ] **DM output routing** in `teleclaude/adapters/telegram/message_ops.py`:
  - `send_message` must handle DM sessions: when adapter metadata contains `dm_chat_id`
    (and no `message_thread_id`), send to `dm_chat_id` directly.
  - Use the same single-persistent-message editing pattern: create one output message
    in the DM chat, store its `message_id`, edit it on each output update.
  - Detect DM vs supergroup from adapter metadata presence of `dm_chat_id`.

- [ ] **DM adapter metadata extension**:
  - Add `dm_chat_id: int | None` and `dm_user_id: int | None` optional fields to
    `TelegramAdapterMetadata` in `teleclaude/core/models.py`.

- [ ] **Session-per-DM-user tracking**:
  - On DM message: query DB for active session with matching `dm_user_id` in adapter
    metadata. If found, reuse. If not, create new.
  - One active session per DM user at a time.
  - When session ends, next DM creates a new session.

- [ ] **Whitelist scoping**:
  - `user_whitelist` remains for supergroup access only (admin control room).
  - DMs bypass the whitelist — identity resolution handles authorization.
  - Unknown DM users get routed to `help-desk` (not rejected).

## Phase 4: Home Routing + Profile-Based Launch

The routing trap and dual-profile agent configuration.

- [ ] **Refactor `AGENT_PROTOCOL`** in `teleclaude/constants.py`:
  - Add `profiles` dict alongside existing `flags`:
    - `"default"`: current `flags` value (unchanged).
    - `"restricted"`: safe flags per research specs (e.g., Claude: no
      `--dangerously-skip-permissions`; Gemini: `--sandbox`).
  - Keep `flags` key as-is for backward compatibility — it remains the `default` profile.
  - Add `HELP_DESK_HOME` constant: `os.path.join(WORKING_DIR, "help-desk")`.

- [ ] **Role-to-tier mapping** in `teleclaude/constants.py`:
  - Define `ADMIN_ROLES = {"admin"}`.
  - Define `TRUSTED_ROLES = {"member", "contributor"}`.
  - Define `JAILED_ROLES = {"newcomer"}`.
  - Helper: `is_trusted(role: str) -> bool` returns `role in ADMIN_ROLES | TRUSTED_ROLES`.

- [ ] **Update `get_agent_command`** in `teleclaude/core/agents.py`:
  - Accept optional `profile: str = "default"`.
  - If `profile` specified, look up `agent_config.profiles[profile]` for flags.
  - Fall back to `flags` (the default profile) if profiles dict doesn't exist.

- [ ] **Home routing in `create_session`** in `teleclaude/core/command_handlers.py`:
  - After identity resolution (Phase 2):
    - If origin is external adapter (telegram, web, whatsapp, discord):
      - Identity resolved with home → override `project_path` to person's `home`,
        `profile="default"`.
      - Identity resolved without home → no project_path override, `profile="default"`.
      - Identity None (unauthorized) → override `project_path` to `HELP_DESK_HOME`,
        `profile="restricted"`.
      - Identity with role in `JAILED_ROLES` → same as unauthorized (help-desk + restricted).
    - If origin is `tui` or `mcp` → no override (current behavior preserved).
  - Pass selected `profile` through to `get_agent_command`.
  - Log the routing decision (identity → home → profile).

## Phase 5: Project Scaffolding + Jailing

- [ ] **Create `help-desk/`** directory in repo root.
- [ ] **Claude security**: `help-desk/.claude/settings.json` with deny rules:
  - Deny `../*` (parent traversal).
  - Deny common system paths.
  - Allow `~/.teleclaude/docs` for knowledge access.
- [ ] **Person home setup**: ensure Mo's `home` in `PersonEntry` points to a real folder
      and per-person `teleclaude.yml` has `creds.telegram.user_id` set.

## Phase 6: Human Role Tool Gating

- [ ] **Tool gating** in MCP wrapper:
  - Add `HUMAN_ROLE_EXCLUDED_TOOLS` dict parallel to AI role filtering in
    `teleclaude/mcp/role_tools.py`.
  - `admin`: no restrictions.
  - `trusted` (member/contributor): exclude `teleclaude__deploy`,
    `teleclaude__end_session` (others'), `teleclaude__mark_agent_status`.
  - `unauthorized`/`newcomer`: handled by restricted profile + jail (no extra gating needed
    beyond what the jail provides).
  - Wrapper reads `human_role` from session DB record (looked up by `caller_session_id`).

## Phase 7: Documentation

- [ ] **Operator guide** (`docs/project/procedure/onboarding-people.md`):
  - Step-by-step: add person to config, set up creds, create home folder, verify.
  - Cover Telegram setup (DM the bot) and future adapter patterns.
  - Include troubleshooting (identity not resolving, session in wrong home).

- [ ] **Person quickstart** (`help-desk/README.md`):
  - What the person sees when they DM the bot.
  - What their personal assistant can do.
  - How to get help.

- [ ] **Architecture doc** (`docs/project/design/home-routing.md`):
  - Identity resolution flow (origin → channel_metadata → resolver → IdentityContext).
  - Routing decision tree (identity → home → profile → agent launch).
  - Jailing mechanics for unauthorized users.
  - Telegram DM channel lifecycle (create session, message flow, session end).
  - Extension points for future adapters (Discord, WhatsApp).

## Phase 8: Verification

- [ ] Unit test: `IdentityResolver.resolve("telegram", {"user_id": known_id})` returns
      person with home.
- [ ] Unit test: `IdentityResolver.resolve("telegram", {"user_id": unknown_id})` returns None.
- [ ] Unit test: `create_session` overrides `project_path` to person's home for known
      telegram user with home set.
- [ ] Unit test: `create_session` overrides `project_path` to `help-desk` for unknown user.
- [ ] Unit test: `create_session` does NOT override for TUI origin.
- [ ] Unit test: `create_session` does NOT override for known person with `home=None`.
- [ ] Unit test: child session inherits parent identity.
- [ ] Unit test: `newcomer` role gets restricted profile and help-desk routing.
- [ ] Unit test: human role tool filtering blocks expected tools for member/contributor.
- [ ] Manual: DM the bot as known user → verify session in home.
- [ ] Manual: DM the bot as unknown user → verify session in help-desk, jail works.

## Files Changed

| File                                             | Change                                       |
| ------------------------------------------------ | -------------------------------------------- |
| `teleclaude/config/schema.py`                    | Add `home` to `PersonEntry`                  |
| `teleclaude/core/identity.py`                    | Extend resolver + add `home`/`name` to ctx   |
| `teleclaude/core/migrations/008_*.py`            | New migration for identity columns           |
| `teleclaude/core/db_models.py`                   | Add identity columns                         |
| `teleclaude/core/models.py`                      | Add identity to SessionSummary + DM metadata |
| `teleclaude/api_models.py`                       | Add identity to DTO                          |
| `teleclaude/core/command_handlers.py`            | Resolve + stamp + route to home              |
| `teleclaude/constants.py`                        | Profiles + HELP_DESK_HOME + role tiers       |
| `teleclaude/core/agents.py`                      | Profile-based launch                         |
| `teleclaude/adapters/telegram_adapter.py`        | DM handler registration                      |
| `teleclaude/adapters/telegram/input_handlers.py` | DM message handling + user_id in metadata    |
| `teleclaude/adapters/telegram/message_ops.py`    | DM output routing                            |
| `teleclaude/mcp/role_tools.py`                   | Human role tool filtering                    |
| `help-desk/`                                     | New project directory + jail config          |
| `docs/project/procedure/onboarding-people.md`    | Operator onboarding guide                    |
| `docs/project/design/home-routing.md`            | Architecture doc                             |
| `tests/unit/test_identity.py`                    | New + extended tests                         |
