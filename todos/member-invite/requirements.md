# Requirements: member-invite

## Goal

Implement the complete member invite and personal assistant onboarding flow: generate invite tokens, send multi-platform deep links via email, handle identity binding on first contact, route known members to their personal workspace, and expand notification delivery to support Telegram, Discord, and email channels.

## Scope

### In scope

**1. Invite Token Infrastructure**

- Add `invite_token` field to `PersonConfig` schema (per-person `teleclaude.yml`)
- Token format: `inv_` + 16 random hex chars (e.g., `inv_a8f3b2c9d1e4f071`)
- Auto-generate on `people add` when email is provided
- Regenerate (rotate) on `config invite NAME`
- Token lookup: scan all person configs to find matching `invite_token`

**2. Deep Link Generation**

- Telegram: `https://t.me/{bot_username}?start={invite_token}` — resolve `bot_username` from live `TELEGRAM_BOT_TOKEN` via `bot.get_me().username`
- Discord: `https://discord.com/users/{bot_user_id}` — resolve bot user ID from `DISCORD_BOT_TOKEN` or config. Person sends token as first DM
- WhatsApp: `https://wa.me/{business_number}?text={invite_token}` — resolve from `WHATSAPP_BUSINESS_NUMBER` env var. Link works at WhatsApp client level even before adapter ships
- All three links use the same invite token

**3. Email Delivery Infrastructure**

- New module: `teleclaude/notifications/email.py` — Brevo SMTP sender
- Env vars: `BREVO_SMTP_USER`, `BREVO_SMTP_PASS`, `BREVO_SENDER_EMAIL`, `BREVO_SENDER_NAME`
- HTML email template: `templates/emails/member-invite.html` — styled platform buttons (Telegram, Discord, WhatsApp), responsive, plain-text fallback
- Template variables: `{name}`, `{org_name}`, `{telegram_link}`, `{discord_link}`, `{whatsapp_link}`, `{sender_name}`
- Function: `send_invite_email(person_name, email, links)` — renders template, sends via SMTP

**4. Fix `telec config invite`**

- Generate/rotate invite token, persist to per-person config
- Resolve bot username from live Telegram bot token
- Resolve bot user ID from Discord bot token
- Generate all three platform deep links
- Send invite email via Brevo SMTP
- Print confirmation: "Invite sent to {email} for {name}"
- `--json` support for programmatic output

**5. Auto-invite on `people add`**

- When `people add` is called with `--email`, auto-trigger the invite flow after person creation
- Skip email if `--no-invite` flag is passed
- Print: "Added {name} — invite sent to {email}"

**6. Telegram Private Chat Handler**

- Add `ChatType.PRIVATE` message handling to the Telegram adapter
- Parse `/start {invite_token}` payload from private chat messages
- Token validation:
  - No match → respond "I don't recognize this invite. Please contact your admin."
  - Match, person not yet bound → store sender's `telegram.user_id` and `telegram.user_name` in per-person config (credential bind)
  - Match, already bound (same user) → resume/create session in personal workspace
  - Match, already bound (different user) → reject: "This invite is already associated with another account."
- After successful binding, create session in `~/.teleclaude/people/{name}/workspace/`
- Personal assistant greets by name

**7. Discord DM Handler**

- Handle DMs (non-guild messages) to the bot
- Parse invite token from first DM message
- Same token validation and credential binding logic as Telegram
- After binding, create session in personal workspace
- Subsequent DMs from bound users route directly to their personal assistant

**8. Personal Assistant Session Routing**

- When identity resolution returns a known person (admin/member/contributor), the session's `project_path` must be `~/.teleclaude/people/{name}/workspace/` instead of `help_desk_dir`
- This routing decision happens at session creation time in each adapter
- The adapter resolves identity FIRST, then selects project path based on role:
  - Known person → personal workspace
  - Unknown/newcomer/customer → `help_desk_dir`
- Workspace scaffolding: create `~/.teleclaude/people/{name}/workspace/` on first session if it doesn't exist
  - Copy `AGENTS.master.md` from person's home folder into workspace (or symlink)
  - Create minimal `teleclaude.yml` for the workspace project
- Existing adapter metadata (Discord thread_id/channel_id, Telegram topic_id) continues to handle response routing back to the correct channel/thread — no changes needed there

**9. Notification Delivery Expansion**

- Extend `NotificationOutboxWorker._deliver_row()` to support three delivery channels:
  - `telegram` — existing `send_telegram_dm()` (no change)
  - `discord` — new `teleclaude/notifications/discord.py` with `send_discord_dm(user_id, content, file=None)` via Discord bot API
  - `email` — new `teleclaude/notifications/email.py` with `send_email(to, subject, html_body, text_body=None, file=None)` via Brevo SMTP
- Worker routes based on `delivery_channel` field in outbox row
- Remove the "not implemented" failure path for non-telegram channels

### Out of scope

- WhatsApp adapter message handling (separate todo: `help-desk-whatsapp`)
- Customer-facing invite flow (customers arrive organically)
- Multi-org/multi-tenant support
- Invite link time-based expiry
- Self-service invite portal or web UI
- Changes to existing admin project routing (supergroup topics, project sessions via MCP/REST)
- Web adapter private chat handling (future work)

## Success Criteria

- [ ] `telec config invite "Maurice Faber"` generates `inv_` token, resolves bot usernames, sends email to `maurice@instrukt.ai` with three platform links
- [ ] `telec config people add --name "New Person" --email new@test.com --role member` auto-sends invite email
- [ ] Clicking the Telegram link opens a private chat with the bot; `/start {token}` binds the user's Telegram credentials in per-person config
- [ ] Clicking the Discord link opens a DM with the bot; sending the token binds Discord credentials
- [ ] WhatsApp link opens WhatsApp client with the token prefilled (delivery deferred to adapter todo)
- [ ] After binding, subsequent messages from the person route to `~/.teleclaude/people/{name}/workspace/` not `help_desk_dir`
- [ ] Personal assistant session loads the person's `AGENTS.master.md` and greets by name
- [ ] Identity-scoped memories are injected into personal assistant sessions
- [ ] Unknown users arriving via private chat/DM with no valid token are directed to contact admin
- [ ] Unknown users arriving via help desk channels (Discord forum, etc.) continue routing to `help_desk_dir` as before
- [ ] Notification outbox successfully delivers via all three channels: Telegram DM, Discord DM, email
- [ ] Already-bound credentials are never overwritten (re-clicking the link resumes the session)
- [ ] Invite token rotation works: `config invite NAME` generates new token, old links stop working
- [ ] Admin/project sessions in Telegram supergroup topics and Discord server channels are UNAFFECTED by the routing changes

## Constraints

- Invite tokens have no time-based expiry — valid until rotated by a new `config invite` call
- Bot username MUST be resolved from live token (not hardcoded) — if token is invalid, command fails before sending email
- WhatsApp link is generated even without a WhatsApp adapter — the link works at the client level, message handling comes later
- Existing adapter metadata routing (thread_id, channel_id, topic_id) must not be disrupted — response routing back to the user continues via adapter metadata
- Brevo SMTP credentials are required for email delivery — if missing, invite prints links to stdout without sending email (graceful degradation)
- Personal workspace creation is lazy — scaffolded on first session, not on invite send
- The identity resolution layer already exists and works — this todo extends the routing decision that follows resolution, not the resolution itself

## Risks

- **Brevo SMTP credentials not configured**: Graceful degradation — print links to stdout, warn about missing email config
- **Bot token invalid or expired**: Fail early with clear error before attempting email send
- **Discord bot cannot DM users**: Discord requires the user to share a server with the bot or have DMs enabled — include fallback instructions in the email
- **Private chat flood**: Rate limiting on `/start` handler to prevent abuse from unknown users
- **Workspace conflicts**: Two adapters creating workspace simultaneously — use `os.makedirs(exist_ok=True)` for idempotent creation
- **Person config file contention**: Multiple processes writing `invite_token` or credentials — use atomic write (write to temp, rename)
- **Token collision**: `inv_` + 16 hex chars = 64-bit space. Collision probability is negligible for any realistic number of people

## Reference Documents

- `docs/project/procedure/member-onboarding.md` — canonical procedure spec
- `docs/project/design/architecture/help-desk-platform.md` — architecture (identity resolution, member folders, session routing)
- `docs/project/spec/messaging.md` — messaging tools and notification infrastructure
- `teleclaude/notifications/worker.py` — notification outbox worker (extend for Discord/email)
- `teleclaude/notifications/telegram.py` — reference implementation for platform sender
- `teleclaude/core/identity.py` — identity resolution (already resolves Telegram/Discord users)
- `teleclaude/adapters/discord_adapter.py:1018` — current routing to `help_desk_dir` (needs conditional)
- `teleclaude/cli/config_cli.py:450-496` — current broken invite handler (needs rewrite)
- `teleclaude/config/schema.py:250` — `PersonConfig` model (needs `invite_token` field)
