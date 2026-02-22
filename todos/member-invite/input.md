# Input: member-invite

## Source

Requirements gathered from:

- User brainstorming session (2026-02-21) covering invite links, personal assistant routing, email delivery, Discord/WhatsApp deep links
- `docs/project/procedure/member-onboarding.md` — fully specified procedure with gap analysis table
- `docs/project/design/architecture/help-desk-platform.md` — architecture covering identity resolution, member personal folders, session routing
- Prior delivery `help-desk-platform` (commit `7156e94a`) — designed the system but did not implement invite/onboarding flow
- Prior delivery `help-desk-discord` (commit `619c71d3`) — Discord adapter routes to `help_desk_dir`, no personal home folder routing
- Prior delivery `role-based-notifications` (commit `27c4fbfd`) — notification outbox exists but only Telegram sender is implemented
- Existing code: `telec config invite` (commit `6af11119`) — scaffolded but broken (no token, no bot username, no email)

## Context

TeleClaude has a working help desk where customers arrive via Discord threads and get AI-handled sessions. That works. What does NOT work is the member/admin invite flow — the entire path from "admin adds a person" to "person clicks a link and lands in their personal AI assistant session."

The personal assistant is the member-facing counterpart to the customer-facing help desk. Each member gets:

- A persistent home folder at `~/.teleclaude/people/{name}/`
- An `AGENTS.master.md` that defines their personal assistant's brain
- A `teleclaude.yml` with their credentials and preferences
- A workspace subfolder (`~/.teleclaude/people/{name}/workspace/`) where sessions run

The invite feature is the onboarding gate: send an email with platform deep links, person clicks one, identity is bound, and they land in their personal assistant.

## What exists today

### Working

- Person config model (`PersonEntry` in schema.py) with name, email, role, username
- Per-person config (`PersonConfig`) with creds (Telegram, Discord), notifications, subscriptions
- Per-person home folders (`~/.teleclaude/people/{name}/`) with `teleclaude.yml` and `AGENTS.master.md`
- Identity resolution (`teleclaude/core/identity.py`) — resolves Telegram/Discord users to configured persons by platform credentials
- Notification outbox (`notification_outbox` table, `NotificationOutboxWorker`) — durable delivery with retry
- Telegram notification sender (`teleclaude/notifications/telegram.py`) — `send_telegram_dm()`
- `telec config people add/edit/remove/list` — CRUD for person entries
- `telec config invite NAME` — exists but broken (see below)
- Help desk bootstrap — `templates/help-desk/` + `help_desk_bootstrap.py`
- Discord adapter routing — customers routed to `config.computer.help_desk_dir` with rich adapter metadata (user_id, guild_id, channel_id, thread_id)
- Discord adapter session lookup via thread_id and channel_id (`get_sessions_by_adapter_metadata`)
- Telegram adapter metadata — topic_id, user_id, output_message_id

### Broken / incomplete

- **`telec config invite`**: No invite token generation, no bot username resolution, broken Telegram deep link (`https://t.me/?start=invite_morriz` — missing bot username), no email sending, no Discord link, no WhatsApp link
- **Notification worker**: Only supports `delivery_channel == "telegram"` (worker.py:107-119). Discord and email channels hit "not implemented" and are marked as permanently failed
- **No email sending infrastructure**: No `teleclaude/notifications/email.py`, no Brevo SMTP integration, no email template
- **No Discord DM notification sender**: No `teleclaude/notifications/discord.py` for sending DMs
- **No Telegram private chat handler**: The Telegram adapter only handles supergroup/forum messages. No `/start` payload parsing in private chats. No `ChatType.PRIVATE` handling at all
- **No invite token in PersonConfig schema**: `invite_token` field doesn't exist in the Pydantic model
- **No personal assistant session routing**: All adapter inbound messages route to `help_desk_dir` (Discord: `discord_adapter.py:1018`) or admin projects. No path routes known members/admins to `~/.teleclaude/people/{name}/workspace/`
- **No workspace scaffolding on first session**: `~/.teleclaude/people/{name}/workspace/` is never created

## What the user wants

### Three output channels with working deep links

1. **Telegram**: `https://t.me/{bot_username}?start={invite_token}` — opens Telegram private chat, bot receives `/start` with payload
2. **Discord**: DM deep link to the bot — person sends invite token as first message to bind identity
3. **WhatsApp**: `https://wa.me/{business_number}?text={invite_token}` — opens WhatsApp client with token prefilled

WhatsApp adapter doesn't exist yet (see `help-desk-whatsapp` on roadmap, DOR:10), but the link MUST be generated and work at the WhatsApp client level (opens the app, prefills the token). Actual message handling will come with the WhatsApp adapter delivery.

### Email delivery

- Brevo SMTP integration for sending invite emails
- HTML email template with styled platform buttons
- Plain text fallback
- Sent automatically on `people add` when email is provided
- Resent on `config invite NAME`

### Identity binding via invite token

- `inv_` + 16 hex chars generated per person
- Stored in per-person `teleclaude.yml` as `invite_token`
- Same token embedded in all platform links — the platform they arrive on tells us which credential to store
- On first private message, match token to person config, bind platform credential (user_id)
- Already-bound credentials are never overwritten (same user resumes session; different user is rejected)
- Token rotated on resend (`config invite`)

### Personal assistant session routing

- When a known member/admin arrives via any adapter, route their session to `~/.teleclaude/people/{name}/workspace/` instead of `help_desk_dir`
- The session loads the member's `AGENTS.master.md` as the agent brain
- Memory injection uses identity-scoped memories for that person
- The personal assistant greets them by name
- This is the KEY routing change: identity-aware project path selection

### Notification delivery expansion

- The notification outbox worker must support three delivery channels: `telegram`, `discord`, `email`
- Discord DM sender (via bot's Discord API)
- Email sender (via Brevo SMTP)
- Channel routing respects person's `preferred_channel` or subscription notification config

### Admin/member routing awareness

The existing adapter routing already handles return paths correctly via adapter metadata:

- **Discord**: Rich metadata (user_id, guild_id, channel_id, thread_id) ensures responses route back to the correct thread
- **Telegram**: Metadata (topic_id, user_id) routes back to the correct supergroup topic
- This routing must continue to work as-is for admin project sessions
- The new routing layer sits ABOVE this: it decides WHERE the session lives (help desk vs personal workspace), then the existing adapter metadata handles HOW responses get back to the user

### Routing logic

Current: all Discord/Telegram inbound → `help_desk_dir` (customer help desk)

Required:

```
Incoming message → Identity resolution
  → Known person (admin/member/contributor)?
    → Route to ~/.teleclaude/people/{name}/workspace/
    → Load person's AGENTS.master.md
    → Inject identity-scoped + project-level memories
  → Unknown person (or newcomer with no binding)?
    → Route to help_desk_dir (customer help desk)
    → Customer role, customer-scoped tools
```

This applies to ALL adapters: Telegram private chats, Discord DMs/threads, WhatsApp messages, and future web sessions. The adapter resolves identity first, then the routing layer decides where the session lives. The adapter metadata then handles the return path.

## Dependencies

- `help-desk-whatsapp` (on roadmap, DOR:10) — WhatsApp adapter. Invite link generation is independent; actual message handling depends on that todo.
- No other blocking dependencies. Identity resolution, notification outbox, person config — all exist.

## Non-goals

- Customer-facing invite flow (customers arrive organically via help desk channels)
- Multi-org/multi-tenant support
- Self-service invite portal
- Invite link time-based expiry (tokens are valid until rotated)
- Changes to existing admin project routing (supergroup topics, project sessions stay as-is)
