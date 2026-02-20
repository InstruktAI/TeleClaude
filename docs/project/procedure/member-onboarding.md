---
id: 'project/procedure/member-onboarding'
type: 'procedure'
scope: 'project'
description: 'Invite a new member by email with deep links to their personal AI assistant on Telegram, Discord, or WhatsApp.'
---

# Member Onboarding — Procedure

## Required reads

@docs/project/design/architecture/help-desk-platform.md
@docs/project/spec/messaging.md

## Goal

Send a new member an email containing deep links to start a private conversation with their personal AI assistant. One click opens a chat on their preferred platform. The assistant knows who they are from the first message.

## Preconditions

- At least one adapter is configured (Telegram bot token, Discord bot, or WhatsApp Business number).
- Email delivery is configured (Brevo SMTP credentials in env: `BREVO_SMTP_USER`, `BREVO_SMTP_PASS`, `BREVO_SENDER_EMAIL`).

## Invite token

Each person gets a single `invite_token` stored in their per-person config (`~/.teleclaude/people/{name}/teleclaude.yml`). The same token is embedded in all platform links. The platform the person arrives on tells us which credential to store — the token just answers "who is this person."

- Generated on `people add` (automatic) or `invite` (manual resend).
- Format: `inv_` + 16 random hex chars (e.g., `inv_a8f3b2c9d1e4f071`).
- Stays valid until a new invite is sent, which rotates the token.
- No time-based expiry.
- Already-bound credentials are never overwritten. If telegram is already set and the person clicks the Telegram link again, resume their session — don't re-bind.

## Steps

### 1. Admin adds a person

```bash
telec config people add --name "John Doe" --email john@example.com
```

Adding a person automatically:

1. Creates PersonEntry in global config + per-person directory.
2. Generates an `invite_token`, stores it in per-person config.
3. Resolves the bot username from the live Telegram bot token (`bot.get_me().username`).
4. Generates platform deep links (one per configured adapter), all using the same token:

| Platform | Deep link format                                      | What happens when clicked                                |
| -------- | ----------------------------------------------------- | -------------------------------------------------------- |
| Telegram | `https://t.me/{bot_username}?start={invite_token}`    | Opens private chat with bot, sends `/start` with payload |
| Discord  | `https://discord.com/users/{bot_user_id}`             | Opens DM with the bot (token sent as first message)      |
| WhatsApp | `https://wa.me/{business_number}?text={invite_token}` | Opens WhatsApp chat with token prefilled                 |

5. Composes the onboarding email from a template (see below).
6. Sends via Brevo SMTP.
7. Prints confirmation: "Added John Doe — invite sent to john@example.com".

### 1b. Admin resends invite

```bash
telec config invite "John Doe"
```

For existing people who lost their email or need a fresh link. Generates a new token (invalidating the old one), sends the email again.

### 2. Person clicks a link

The person opens their email, picks a platform, clicks the link. This lands them in a **private chat** with the bot.

#### Telegram private chat flow

The bot receives `/start {invite_token}` in a private chat (not the supergroup). The private chat handler:

1. Extracts the token from the `/start` payload.
2. Searches person configs for a matching `invite_token`.
3. If no match → respond "I don't recognize this invite. Please contact your admin."
4. If the person's `telegram.user_id` is not yet set → store the sender's Telegram user ID and username in per-person config. This is the credential bind — one click, identity locked in.
5. If already bound (same user) → proceed to session.
6. If already bound (different user) → reject. "This invite is already associated with another account."
7. Creates a session in the person's workspace folder (`~/.teleclaude/people/{name}/workspace/`), with `human_role` and `human_email` from config.
8. The personal assistant greets them by name.

#### Discord DM flow

Same principle: bot receives a DM containing the token, looks up the person, binds Discord user ID if not yet set, creates/resumes session.

#### WhatsApp flow

Same principle via WhatsApp Business API. The prefilled token text identifies the person on first message.

### 3. First conversation

The personal assistant session starts with:

- Identity-scoped memory injection (empty on first visit, builds over time)
- Organization docs available via `get_context` (the org domain)
- The person's name and role from config
- A welcome message: "Hi {name}, I'm your personal assistant. What would you like to work on?"

## Email template

Subject: **Welcome to {org_name} — Your Personal AI Assistant**

Body (HTML with plain text fallback):

```
Hi {name},

You now have a personal AI assistant. Pick any platform below to start chatting:

[Telegram button] [Discord button] [WhatsApp button]

Just click one — you'll land in a private conversation. Your assistant knows who you are and remembers your history across sessions.

If you have questions, reply to this email.

— {sender_name}
```

Each button is a styled link to the corresponding deep link. The template lives at `templates/emails/member-invite.html`.

## What needs to exist (current gaps)

| Component                             | Status           | What's needed                                                                                               |
| ------------------------------------- | ---------------- | ----------------------------------------------------------------------------------------------------------- |
| `telec config invite`                 | Exists, broken   | Fix bot username resolution, send email, validate email exists                                              |
| `telec config people add` auto-invite | Missing          | Trigger invite on add when email is provided                                                                |
| Invite token generation               | Missing          | Generate `inv_` + 16 hex chars, store in per-person config                                                  |
| Telegram private chat handler         | Missing          | `/start` command handler for `ChatType.PRIVATE` with payload parsing                                        |
| Email sending                         | Missing          | Brevo SMTP integration (`teleclaude/notifications/email.py`)                                                |
| Email template                        | Missing          | `templates/emails/member-invite.html`                                                                       |
| Discord DM handler                    | Missing          | DM message handler with identity resolution                                                                 |
| WhatsApp adapter                      | Missing (icebox) | Out of scope for MVP — include link in email anyway                                                         |
| Person workspace creation             | Partially exists | `~/.teleclaude/people/{name}/` exists in config, `/workspace/` subfolder needs scaffolding on first session |
| Token-based credential binding        | Missing          | On first private message, match invite token → bind platform user ID to PersonEntry                         |

## MVP scope

Telegram + email only. Discord and WhatsApp links are generated in the email but land on a "coming soon" or simply don't resolve until those adapters support private chats. The Telegram flow is the critical path:

1. Invite token generation + storage in per-person config
2. `people add` auto-sends invite email when email is provided
3. `invite` resends with fresh token
4. Brevo SMTP email sending
5. Telegram private chat `/start` handler with token-based credential binding
6. Session creation in personal workspace

## Outputs

- Adding a person with an email automatically sends the invite.
- Person receives an email with working platform links (one token, all platforms).
- Clicking a link starts a private chat; token proves identity, platform credential is bound.
- Personal workspace folder is created on first session.
- `invite` resends with a fresh token when needed.

## Recovery

- If email fails to send: command prints error with SMTP details, admin can retry.
- If person clicks expired/invalid link: bot responds with "I don't recognize this invite. Please contact your admin."
- If person already onboarded: clicking the link again resumes their existing session.
- If bot username resolution fails (token invalid): command fails with clear error before sending email.
