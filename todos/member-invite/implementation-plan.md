# Implementation Plan: member-invite

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the complete member invite and personal assistant onboarding flow: invite tokens, email delivery, private chat handlers, identity binding, personal workspace routing, and notification channel expansion.

**Architecture:** Extends the existing identity resolution and notification subsystems. Adds invite token generation to per-person config, Brevo SMTP email delivery, Telegram private chat `/start` handler, Discord DM handler, identity-aware session routing (personal workspace vs help desk), and Discord/email senders to the notification outbox worker.

**Tech Stack:** Python 3.12, python-telegram-bot (existing), discord.py (existing), httpx, Brevo SMTP (aiosmtplib + email.mime), Pydantic config, ruamel.yaml

**Design docs:**

- `docs/project/procedure/member-onboarding.md`
- `docs/project/design/architecture/help-desk-platform.md` (§Identity Resolution, §Member Personal Folders)

**Key reference files:**

- `teleclaude/core/identity.py` — identity resolution (extend for invite token lookup)
- `teleclaude/cli/config_cli.py:450-496` — broken invite handler (rewrite)
- `teleclaude/cli/config_handlers.py` — `add_person()`, `save_person_config()`, `get_person_config()`
- `teleclaude/notifications/worker.py` — outbox worker (extend for discord/email channels)
- `teleclaude/notifications/telegram.py` — reference sender implementation
- `teleclaude/adapters/telegram_adapter.py:534-577` — handler registration (add private chat handler)
- `teleclaude/adapters/discord_adapter.py:1012-1029` — session creation routing (add identity-aware path)
- `teleclaude/config/schema.py:250` — PersonConfig model (add invite_token)

---

## Phase 1: Invite Token Infrastructure

### Task 1.1: Add invite_token to PersonConfig schema

**File(s):** `teleclaude/config/schema.py`

- [x] Add `invite_token: Optional[str] = None` field to `PersonConfig` (line ~252, after `creds`)
- [x] Add `notifications: Optional[dict] = None` is already handled by `extra="allow"` but `invite_token` should be explicit

### Task 1.2: Add token generation and persistence helpers

**File(s):** `teleclaude/cli/config_handlers.py`

- [x] Add `generate_invite_token() -> str` function: `"inv_" + secrets.token_hex(8)` (16 hex chars)
- [x] Add `set_invite_token(name: str) -> str` function: generates token, loads person config, sets `invite_token`, saves atomically via `save_person_config()`, returns the token
- [x] Add `find_person_by_invite_token(token: str) -> tuple[str, PersonConfig] | None` function: scans all `~/.teleclaude/people/*/teleclaude.yml` files, returns (person_name, config) if matching `invite_token` found

### Task 1.3: Add bot username/ID resolution helpers

**File(s):** `teleclaude/cli/config_handlers.py` (or new `teleclaude/invite.py`)

- [x] Add `async resolve_telegram_bot_username(token_env="TELEGRAM_BOT_TOKEN") -> str` function: calls Telegram `getMe` API via httpx, returns `bot.username`
- [x] Add `async resolve_discord_bot_user_id(token_env="DISCORD_BOT_TOKEN") -> str` function: calls Discord `GET /users/@me` API via httpx, returns bot user ID
- [x] Both raise `ValueError` with clear message if token missing or API fails

### Task 1.4: Add deep link generation

**File(s):** `teleclaude/invite.py` (new module)

- [x] Create `teleclaude/invite.py` with invite link generation logic
- [x] `generate_invite_links(token: str, bot_username: str | None, discord_bot_id: str | None, whatsapp_number: str | None) -> dict[str, str | None]`:
  - Telegram: `https://t.me/{bot_username}?start={token}` (None if no bot_username)
  - Discord: `https://discord.com/users/{discord_bot_id}` (None if no bot ID)
  - WhatsApp: `https://wa.me/{whatsapp_number}?text={token}` (None if no number)
- [x] Links that cannot be generated return None with a reason string

**Step: Run tests**

Run: `pytest tests/unit/test_invite.py -v` (create test file)

**Step: Commit**

```
feat(invite): add token generation, bot resolution, and deep link helpers
```

---

## Phase 2: Email Delivery Infrastructure

### Task 2.1: Create Brevo SMTP email sender

**File(s):** `teleclaude/notifications/email.py` (new)

- [ ] Create `teleclaude/notifications/email.py`
- [ ] `async send_email(to: str, subject: str, html_body: str, text_body: str | None = None, *, smtp_host: str = "smtp-relay.brevo.com", smtp_port: int = 587) -> None`
- [ ] Read credentials from env: `BREVO_SMTP_USER`, `BREVO_SMTP_PASS`, `BREVO_SENDER_EMAIL`, `BREVO_SENDER_NAME`
- [ ] Use `aiosmtplib` for async SMTP or `smtplib` in a thread via `asyncio.to_thread`
- [ ] Build MIME multipart message: HTML body + plain text alternative
- [ ] Raise `ValueError` if credentials missing, `RuntimeError` on SMTP failure

### Task 2.2: Create invite email template

**File(s):** `templates/emails/member-invite.html` (new), `templates/emails/member-invite.txt` (new)

- [ ] Create `templates/emails/member-invite.html` — responsive HTML email with:
  - Greeting: "Hi {name},"
  - Intro: "You now have a personal AI assistant. Pick any platform below to start chatting:"
  - Three styled button links: Telegram (blue), Discord (indigo), WhatsApp (green)
  - Buttons that have no link (None) are hidden or shown as "coming soon"
  - Footer: "Just click one — you'll land in a private conversation. Your assistant knows who you are."
  - Sign-off: "— {sender_name}"
- [ ] Create `templates/emails/member-invite.txt` — plain text fallback with the same info
- [ ] Template uses `{name}`, `{telegram_link}`, `{discord_link}`, `{whatsapp_link}`, `{sender_name}`, `{org_name}` placeholders (simple str.format)

### Task 2.3: Create invite email composition function

**File(s):** `teleclaude/invite.py`

- [ ] Add `async send_invite_email(name: str, email: str, links: dict[str, str | None], org_name: str = "InstruktAI", sender_name: str = "Your Admin") -> None`
- [ ] Load templates from `templates/emails/member-invite.{html,txt}`
- [ ] Substitute placeholders
- [ ] Call `send_email()` with subject "Welcome to {org_name} — Your Personal AI Assistant"
- [ ] If `BREVO_SMTP_USER` is missing, print links to stdout as fallback (graceful degradation)

**Step: Run tests**

Run: `pytest tests/unit/test_email_sender.py -v` (create test file, mock SMTP)

**Step: Commit**

```
feat(notifications): add Brevo SMTP email sender and invite email template
```

---

## Phase 3: Fix `telec config invite` and Auto-invite

### Task 3.1: Rewrite `_handle_invite` in config_cli.py

**File(s):** `teleclaude/cli/config_cli.py:450-496`

- [ ] Rewrite `_handle_invite()`:
  1. Validate person exists (keep existing check)
  2. Call `set_invite_token(name)` to generate/rotate token
  3. Call `resolve_telegram_bot_username()` (sync wrapper or asyncio.run for CLI context)
  4. Call `resolve_discord_bot_user_id()` (same)
  5. Read `WHATSAPP_BUSINESS_NUMBER` from env
  6. Call `generate_invite_links(token, bot_username, discord_bot_id, whatsapp_number)`
  7. Look up person's email from global config
  8. Call `send_invite_email(name, email, links)` (async, wrapped for CLI)
  9. Print confirmation: "Invite sent to {email} for {name}"
  10. `--json` output: `{"ok": true, "name": ..., "email": ..., "links": {...}}`
- [ ] Handle errors: missing bot token → warn but continue with available links; missing email → fail with clear message

### Task 3.2: Add auto-invite on `people add`

**File(s):** `teleclaude/cli/config_cli.py:174-210`

- [ ] After `add_person(entry)` succeeds, if email is present and `--no-invite` not in args:
  1. Call `set_invite_token(name)`
  2. Resolve bot usernames
  3. Generate links
  4. Send invite email
  5. Print: "Added {name} as {role} — invite sent to {email}"
- [ ] If `--no-invite` is passed, skip invite flow

**Step: Run tests**

Run: `pytest tests/unit/test_config_cli.py -v`

**Step: Commit**

```
feat(config): rewrite invite with token generation, email delivery, and auto-invite on people add
```

---

## Phase 4: Telegram Private Chat Handler

### Task 4.1: Add private chat `/start` handler

**File(s):** `teleclaude/adapters/telegram_adapter.py`

- [ ] In `start()` method (around line 534), add a new handler BEFORE the supergroup text handler:
  ```python
  private_start_handler = CommandHandler(
      "start",
      self._handle_private_start,
      filters=filters.ChatType.PRIVATE,
  )
  self.app.add_handler(private_start_handler)
  ```
- [ ] Add `async _handle_private_start(self, update, context)`:
  1. Extract `/start {payload}` — the payload is `context.args[0]` if present
  2. If no payload or payload doesn't start with `inv_` → respond "Send me your invite token to get started, or contact your admin for an invite link."
  3. Call `find_person_by_invite_token(payload)` (from config_handlers)
  4. If no match → respond "I don't recognize this invite. Please contact your admin."
  5. If match:
     a. Load person config
     b. Check if `creds.telegram.user_id` is already set:
     - Same user → proceed to session (already bound)
     - Different user → respond "This invite is already associated with another account."
     - Not set → bind: set `creds.telegram.user_id` and `creds.telegram.user_name` from the sender, save person config atomically
       c. Create session in `~/.teleclaude/people/{name}/workspace/` (scaffold workspace if needed)
       d. Respond: "Hi {name}, I'm your personal assistant. What would you like to work on?"

### Task 4.2: Add private chat text handler for bound users

**File(s):** `teleclaude/adapters/telegram_adapter.py`

- [ ] Add handler for `ChatType.PRIVATE & TEXT & ~COMMAND`:
  ```python
  private_text_handler = MessageHandler(
      filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
      self._handle_private_text,
  )
  self.app.add_handler(private_text_handler)
  ```
- [ ] In `_handle_private_text(self, update, context)`:
  1. Get sender's `user_id` from `update.effective_user.id`
  2. Resolve identity via `IdentityResolver` (already resolves by `telegram_user_id`)
  3. If known person → route message to their personal workspace session (find or create)
  4. If unknown → respond "I don't recognize your account. Use an invite link to get started."

### Task 4.3: Add workspace scaffolding helper

**File(s):** `teleclaude/invite.py`

- [ ] Add `scaffold_personal_workspace(person_name: str) -> Path`:
  - Target: `~/.teleclaude/people/{person_name}/workspace/`
  - `os.makedirs(exist_ok=True)`
  - If `AGENTS.master.md` exists in person's home folder, symlink or copy to workspace
  - If no `AGENTS.master.md` in home folder, create minimal default: "You are the personal assistant of {person_name}."
  - Create minimal `teleclaude.yml` in workspace if not present
  - Return the workspace path

**Step: Run tests**

Run: `pytest tests/unit/test_telegram_private.py -v` (create test file)

**Step: Commit**

```
feat(telegram): add private chat /start handler with invite token binding and personal workspace routing
```

---

## Phase 5: Discord DM Handler

### Task 5.1: Add Discord DM message handling

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] In the `on_message` handler path, detect DM context:
  - Check if `message.guild is None` (DMs have no guild)
  - If DM and message content matches `inv_` prefix → invite token binding flow (same logic as Telegram: find person, check binding, bind credentials, create workspace session)
  - If DM and user is already bound → route to personal workspace session
  - If DM and user is unknown (no token, no binding) → respond "Send me your invite token to get started."
- [ ] The DM handler sits before the existing guild-based routing

### Task 5.2: Add Discord credential binding

**File(s):** `teleclaude/invite.py`

- [ ] Add `bind_discord_credentials(person_name: str, discord_user_id: str) -> None`: loads person config, sets `creds.discord.user_id`, saves atomically
- [ ] Reuse the same `find_person_by_invite_token()` for token lookup
- [ ] Same binding rules: already bound same user → proceed, different user → reject, not bound → bind

**Step: Run tests**

Run: `pytest tests/unit/test_discord_dm.py -v` (create test file)

**Step: Commit**

```
feat(discord): add DM handler with invite token binding and personal workspace routing
```

---

## Phase 6: Personal Assistant Session Routing

### Task 6.1: Add identity-aware project path selection

**File(s):** `teleclaude/invite.py`

- [ ] Add `resolve_project_path(identity: IdentityContext | None) -> str`:
  - If identity is None or identity.person_role in ("customer", "newcomer", None) → return `config.computer.help_desk_dir`
  - If identity.person_name is set and role is admin/member/contributor → return `~/.teleclaude/people/{person_name}/workspace/`
  - Scaffold workspace if it doesn't exist (call `scaffold_personal_workspace`)
  - Fallback: `config.computer.help_desk_dir`

### Task 6.2: Update Discord adapter session creation to use identity-aware routing

**File(s):** `teleclaude/adapters/discord_adapter.py:1012-1029`

- [ ] In `_create_session_for_message()`, before `CreateSessionCommand`:
  1. Resolve identity: `identity = get_identity_resolver().resolve("discord", {"user_id": user_id, "discord_user_id": user_id})`
  2. Call `resolve_project_path(identity)` to get the project path
  3. Replace hardcoded `config.computer.help_desk_dir` with the resolved path
  4. Set `human_role` from identity if available (instead of hardcoded `"customer"`)
- [ ] Existing adapter metadata (channel_id, thread_id, guild_id) is UNCHANGED — response routing back to threads continues as before

### Task 6.3: Verify Telegram adapter routing (private chat sessions)

**File(s):** `teleclaude/adapters/telegram_adapter.py`

- [ ] Confirm that private chat sessions created in Task 4.1 use the personal workspace path
- [ ] Confirm that existing supergroup topic sessions are UNAFFECTED (they use topic-based routing, not identity-based routing)
- [ ] The supergroup routing path does NOT change — it already works for admin/project sessions

**Step: Run tests**

Run: `pytest tests/unit/test_routing.py -v` (create test file)

**Step: Commit**

```
feat(routing): identity-aware project path selection — known members route to personal workspace
```

---

## Phase 7: Notification Channel Expansion

### Task 7.1: Create Discord DM notification sender

**File(s):** `teleclaude/notifications/discord.py` (new)

- [ ] Create `teleclaude/notifications/discord.py`
- [ ] `async send_discord_dm(user_id: str, content: str, file: str | None = None, *, token_env: str = "DISCORD_BOT_TOKEN", timeout_s: float = 10.0) -> str`:
  - Open DM channel: `POST /users/@me/channels` with `recipient_id`
  - Send message: `POST /channels/{dm_channel_id}/messages` with content
  - If file: upload as attachment
  - Return message ID
  - Raise on missing token or API failure
- [ ] Follow same pattern as `teleclaude/notifications/telegram.py` (httpx async client, error handling, logging)

### Task 7.2: Extend notification outbox worker for Discord and email

**File(s):** `teleclaude/notifications/worker.py:98-167`

- [ ] In `_deliver_row()`, replace the `if delivery_channel != "telegram"` block (lines 107-119) with a dispatch:
  ```python
  if delivery_channel == "telegram":
      await send_telegram_dm(chat_id=chat_id, content=content, file=file_path_value)
  elif delivery_channel == "discord":
      from .discord import send_discord_dm
      await send_discord_dm(user_id=recipient, content=content, file=file_path_value)
  elif delivery_channel == "email":
      from .email import send_email
      await send_email(to=recipient, subject="Notification", html_body=content)
  else:
      # Unknown channel — fail permanently
      ...
  ```
- [ ] Discord: recipient field contains discord user_id (same convention as telegram chat_id)
- [ ] Email: recipient field contains email address

### Task 7.3: Import and export from notifications **init**.py

**File(s):** `teleclaude/notifications/__init__.py`

- [ ] Add imports for new senders (if the module uses **init** for public API)

**Step: Run tests**

Run: `pytest tests/unit/test_notification_worker.py -v`

**Step: Commit**

```
feat(notifications): add Discord DM and email senders, extend outbox worker for all three channels
```

---

## Phase 8: Validation

### Task 8.1: Integration tests

- [ ] Test invite flow end-to-end: generate token → send email (mocked SMTP) → simulate `/start` with token → verify binding → verify session creation in personal workspace
- [ ] Test Discord DM flow: simulate DM with token → verify binding → verify workspace routing
- [ ] Test routing: known admin via Discord → personal workspace; unknown user via Discord → help desk
- [ ] Test notification delivery for all three channels (mocked senders)
- [ ] Test edge cases: expired/invalid token, already-bound different user, missing bot tokens

### Task 8.2: Quality checks

- [ ] Run `make test`
- [ ] Run `make lint`
- [ ] Verify no existing tests broken by routing changes
- [ ] Verify existing supergroup/forum topic sessions unaffected
- [ ] Verify existing Discord help desk thread routing unaffected

### Task 8.3: Manual verification

- [ ] Run `telec config invite "Maurice Faber"` — verify email arrives with working links
- [ ] Click Telegram link — verify private chat opens, `/start` binds identity, session created in `~/.teleclaude/people/Morriz/workspace/`
- [ ] Send message in Telegram private chat — verify personal assistant responds
- [ ] Verify Discord help desk still works (post in Discord forum → customer session)

**Step: Commit**

```
test(member-invite): add integration tests for invite flow, routing, and notification channels
```

---

## Phase 9: Review Readiness

- [ ] Confirm all requirements from `requirements.md` are reflected in code
- [ ] Confirm all implementation tasks above are marked `[x]`
- [ ] Confirm existing admin/project routing is unaffected (regression check)
- [ ] Document any deferrals in `deferrals.md` if applicable
- [ ] Update `docs/project/procedure/member-onboarding.md` gap table to reflect what's been delivered
