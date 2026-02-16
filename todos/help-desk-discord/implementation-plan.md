# Help Desk Discord — Implementation Plan

## Approach

Fix the Discord routing layer and operational pipeline gaps identified in the post-delivery audit. Batch all critical and high-severity fixes into a single pass. Focus on making the system testable end-to-end.

## Task sequence

### [x] Task 1: Inbound channel gating (R1)

**File:** `teleclaude/adapters/discord_adapter.py`

**Changes:**

1. In `_handle_on_message`, after the escalation channel check (line 354), add:
   - Extract the parent channel ID (for threads) or the channel ID itself
   - If `_help_desk_channel_id` is configured, only proceed if the message is from that forum or a thread within it
   - If message is from any other channel, `return` silently (debug log)
   - Also verify `guild_id` matches `config.discord.guild_id`
2. Helper method: `_is_help_desk_message(message) -> bool`

**Tests:**

- `test_discord_ignores_non_help_desk_channel` — message from random channel → no session created
- `test_discord_processes_help_desk_forum_thread` — message from help-desk thread → session created
- `test_discord_ignores_wrong_guild` — message from different guild → dropped

**Verify:** Run `uv run pytest tests/unit/test_discord_adapter.py -v`

---

### Task 2: Fix `_normalize_role` (R2, R15)

**File:** `teleclaude/core/identity.py`

**Changes:**

1. Replace `_normalize_role` implementation:

   ```python
   VALID_ROLES = {HUMAN_ROLE_ADMIN, HUMAN_ROLE_MEMBER, HUMAN_ROLE_CONTRIBUTOR, HUMAN_ROLE_NEWCOMER, HUMAN_ROLE_CUSTOMER}

   @staticmethod
   def _normalize_role(role: str) -> str:
       if role in VALID_ROLES:
           return role
       return HUMAN_ROLE_CUSTOMER  # unknown roles get most restrictive
   ```

2. Import `HUMAN_ROLE_CONTRIBUTOR`, `HUMAN_ROLE_NEWCOMER`, `HUMAN_ROLE_CUSTOMER` from constants

**Tests:**

- `test_normalize_role_preserves_customer` — `"customer"` → `"customer"`
- `test_normalize_role_preserves_admin` — `"admin"` → `"admin"`
- `test_normalize_role_preserves_member` — `"member"` → `"member"`
- `test_normalize_role_unknown_defaults_to_customer` — `"boss"` → `"customer"`

**Verify:** `uv run pytest tests/unit/test_identity.py -v`

---

### Task 3: Use `help_desk_dir` config (R3)

**File:** `teleclaude/adapters/discord_adapter.py`

**Changes:**

1. In `_create_session_for_message`, replace:
   ```python
   project_path=os.path.join(WORKING_DIR, "help-desk")
   ```
   with:
   ```python
   project_path=config.computer.help_desk_dir
   ```
2. Verify `config.computer.help_desk_dir` exists and has a sensible default. Check `teleclaude/config/__init__.py` for the field.

**Verify:** Read the session record after creation, confirm `project_path` matches config.

---

### Task 4: Fix relay context customer messages (R5)

**File:** `teleclaude/adapters/discord_adapter.py`

**Changes:**

1. In `_collect_relay_messages`, do NOT skip bot messages entirely
2. Instead: if message is from the bot AND matches the forwarding pattern (`**{name}** ({platform}): {text}`), parse it as a customer message
3. If message is from the bot but doesn't match the pattern, skip it (system/notification messages)
4. Fix the `is_admin` heuristic: use the forwarding pattern match instead of `not bot`

**Tests:**

- `test_relay_context_includes_customer_forwarded_messages`
- `test_relay_context_excludes_bot_system_messages`
- `test_relay_context_labels_admin_messages_correctly`

**Verify:** `uv run pytest tests/unit/test_discord_adapter.py -v`

---

### Task 5: Verify escalation notification flow (R4)

**Files:** `teleclaude/mcp/handlers.py`, `teleclaude/adapters/discord_adapter.py`

**Context:** Admin notification relies on Discord's native forum notifications — admins subscribe to the escalation channel and get notified when a thread is created. No separate push notification is needed.

**Changes:**

1. Verify `teleclaude__escalate` creates the thread in the escalation forum (already implemented at `handlers.py:1238`)
2. Verify the relay flow works end-to-end: admin sees thread → interacts → tags `@agent` → history between last agent interaction and the tag is compiled as quoted context → injected into AI session
3. Fix the misleading return message at line 1262 to accurately describe the mechanism ("Escalation thread created in escalation forum. Admins subscribed to the channel will be notified by Discord.")
4. Verify `_is_agent_tag` and `_handle_agent_handback` correctly compile the relay-to-agent context

**Tests:**

- `test_escalation_creates_thread_in_escalation_forum`
- `test_agent_handback_compiles_relay_context` (may already exist)

**Verify:** `uv run pytest tests/unit/test_discord_adapter.py tests/unit/test_help_desk_features.py -v`

---

### ~~Task 6: Telegram relay awareness (R6)~~ — DEFERRED

Cross-adapter relay deferred. Customers stay on their original adapter; converging on Discord for help desk.

---

### Task 7: Wire channel worker notification dispatch (R8)

**File:** `teleclaude/channels/worker.py`

**Changes:**

1. Replace the `notification` log-only stub with actual notification delivery
2. Use adapter_client or the daemon's notification mechanism
3. For `command` type: keep as TODO with clear comment about what needs wiring

**Tests:**

- `test_channel_worker_dispatches_notification`

**Verify:** `uv run pytest tests/unit/test_help_desk_features.py -v`

---

### Task 8: Wire `/compact` injection into extraction job (R7)

**File:** `jobs/session_memory_extraction.py`

**Context:** The two-phase design is already in place:

- `maintenance_service._check_idle_compaction()` detects idle and sets the `last_memory_extraction_at` marker
- `session_memory_extraction` job (scheduled every 30 min) finds sessions with pending extraction
- The gap: after `_process_session()` completes extraction, `/compact` must be injected

**Changes:**

1. In `_process_session()`, after `_update_bookkeeping()`, get the session's `tmux_session_name`
2. Import and call `send_keys_existing_tmux(session.tmux_session_name, "/compact", send_enter=True)`
3. Log the compact injection for observability
4. Wrap in try/except — if the tmux session is gone (already terminated), log warning and continue

**Verify:** Trigger idle compaction in logs, confirm `/compact` appears in tmux output after extraction.

---

### Task 9: Template jobs config + identity key index (R9, R10, R11)

**Files:**

- `templates/help-desk/teleclaude.yml` — add jobs section
- `teleclaude/core/identity.py` — add web platform to `derive_identity_key`
- `teleclaude/core/schema.sql` + new migration — add `(project, identity_key)` index

**Changes:**

1. Template: add `help-desk-session-review` (hourly) and `help-desk-intelligence` (daily) job declarations
2. Identity: add web platform check in `derive_identity_key`
3. Schema: add composite index migration

**Verify:** `uv run pytest tests/unit/test_identity.py tests/unit/test_help_desk_features.py -v`

---

## Risks

- **Channel gating may break existing test sessions** — Ensure the gating only applies when `help_desk_channel_id` is configured (None = process all, for dev/test)
- **`_normalize_role` change affects Telegram** — The function is used for all platforms. Verify Telegram identity tests still pass.
- **Compact injection depends on tmux session still existing** — Wrap in try/except; session may have been terminated between extraction and compact.

## Verification (full pass)

After all tasks:

1. `make lint` — passes
2. `uv run pytest tests/ -x` — all tests pass (excluding known flaky Gemini tests)
3. Manual test: send Discord message in help-desk forum → session created with Claude → agent responds
4. Manual test: send Discord message in #general → no session created
