---
description: 'Messaging tools for Telegram, Discord, and email delivery — results, files, person messages, and escalation.'
visibility: 'public'
---

# Messaging — Spec

## What it is

TeleClaude exposes several messaging tools for agents to deliver content to users. These flows operate through the daemon's Unix socket API (`/tmp/teleclaude-api.sock`) and the `telec` CLI command surface.

Use this when you need to:

- Send formatted text or files to a user session.
- Escalate a help-desk conversation to everyone in the desk's scope.
- Understand which messaging surface to use for a given task.

## Canonical fields

### Messaging command surface

| Command                   | Purpose                                  | Key params                            |
| ------------------------- | ---------------------------------------- | ------------------------------------- |
| `telec sessions result`   | Send markdown/html as a separate message | `content`, `--format`                 |
| `telec sessions file`     | Send a file for download                 | `--path`, `--caption`                 |
| `telec sessions escalate` | Escalate a help-desk visitor to a person | `--customer`, `--reason`, `--summary` |

| `telec message` | Send a message to a person | `<text>`, `--recipient <slug>`, `--file <path>`, `--subject <text>`, `--channel <name>` |

### Person-addressed delivery (`telec message`)

`telec message <text> [--recipient <person-slug>] [--file <path>] [--subject <text>] [--channel <telegram|discord|whatsapp|email>]`
delivers a message to a **person**, decoupled from any session origin. The CLI
handler posts the request over the daemon socket; a core person-messaging
service resolves the recipients and dispatches through the existing outbound
provider primitives (`local/projects/teleclaude/spec/feature/integration/outbound-messaging-providers`)
— the same layer the invitation flow uses. No new transport exists.

<!-- planned-change:cluster-redis-outage-store-and-forward -->

**The master sends.** The person-facing provider sections are master-scoped
(`local/projects/teleclaude/spec/teleclaude-config`), so the master is the one
computer in the fleet that holds a sending credential. A request made on any
other computer is carried to the master by the requesting daemon over the
computer-addressed relay, executed there, and the master's outcome is returned
to the caller as the outcome of the request. The request carries what only the
requesting computer holds: the content of the file `--file` names there, and
the originating session's Discord backlink. The caller addresses a person,
never a computer. When no master is reachable the request fails with that
error; no other computer sends in its place.

<!-- change:cluster-redis-outage-store-and-forward -->

**The master sends.** The person-facing provider sections are master-scoped
(`local/projects/teleclaude/spec/teleclaude-config`), so the master is the one
computer in the fleet that holds a sending credential. A request made on any
other computer is carried to the master by the requesting daemon over the
computer-addressed relay, executed there, and the master's outcome is returned
to the caller as the outcome of the request. The request carries what only the
requesting computer holds: the content of the file `--file` names there, and
the originating session's Discord backlink. The caller addresses a person,
never a computer. While the requesting computer cannot reach the cluster Redis,
the request is held there with what it carries: the caller is told that the
message waits for the master, the request is carried once the master is
reachable, and the master's outcome, a refusal included, is reported to the
caller once it is known. When the cluster Redis answers and no master is live,
the request fails with that error; no other computer sends in its place.

<!-- /planned-change:cluster-redis-outage-store-and-forward -->

**Recipients.** `--recipient` names one person by slug. Without it, the
recipients are resolved from the caller's authority, as
`local/projects/teleclaude/spec/feature/integration/person-addressed-messaging`
specifies.

**Channel resolution — the recipient owns routing.** The person is resolved by
slug through the identity layer. The delivery channel is `--channel` when
supplied, otherwise the `preferred_channel` in the person's own config file
(`local/projects/teleclaude/spec/teleclaude-config`, per-person keys; default `email` when
unset). The resolved channel requires a usable credential on the person's
config — Telegram `chat_id`, Discord `user_id`, WhatsApp `phone_number`; email
uses the person's configured email address and the global SMTP configuration.

**File attachment.** `--file` carries exactly one file. On Telegram and Discord
the message text is the file's caption; on email the file is a MIME attachment
and the text is the body. A file directed at a WhatsApp delivery is refused
with an actionable error (WhatsApp has no media send).

**Subject.** `--subject` sets the email subject line and has no effect on any
other channel. When the resolved channel is email and `--subject` is omitted,
the subject defaults to `TeleClaude message`. The email body carries the
message as plain text plus a minimal HTML rendering derived from it.

**Failure contract.** An unresolvable recipient, a missing credential for the
resolved channel, a channel that cannot carry the request, or a provider send
failure each return a distinct, actionable error to the caller. A message to one
person is delivered in full or not at all, and nothing is dropped silently. A
failed send never cascades to another channel. Delivery to several recipients
reports each recipient's outcome, as
`local/projects/teleclaude/spec/feature/integration/person-addressed-messaging`
specifies.

**Discovery.** `telec config person list` exposes each person's `slug`, so a
caller can discover the addressable identifier.

**Origin backlink (Discord).** When the request carries an originating
TeleClaude session and the resolved channel is discord, the delivered message
ends with that session's native Discord jump link, constructed by the Discord
session-backlink capability
(`local/projects/teleclaude/spec/feature/integration/discord-session-backlink`). A supplied
origin that cannot be resolved to a Discord destination is recorded as a
structured miss and the message is delivered without a backlink. Other
channels render no backlink.

**Origin work item (GitHub).** When the originating session works on an item of
a project on the GitHub workflow store, and the message was delivered, the
requesting computer also hands the message, the resolved recipients, the
session and its Discord jump link when one resolves to that project's store,
which shows it on the item's issue and assigns the recipients
(`local/projects/teleclaude/spec/feature/workflow/github-work-record`). This
never changes the message's delivery or its outcome.

### Transcript normalization (outbound rendering)

Before adapter rendering, transcript entries are normalized into a canonical assistant/user message shape:

- `role`: `user` or `assistant`
- `content[]` block types:
  - `text` / `output_text` for user-visible assistant text
  - `thinking` for model reasoning/thought text
  - `pre_tool_use` / `tool_result` for tool activity

Source mapping is agent-specific but canonical at render time:

- Claude: native `thinking` blocks map directly.
- Gemini: `thoughts[].description` maps to `thinking`.
- Codex: `response_item.payload.type == "reasoning"` maps to `thinking`.

Adapter policy:

- Telegram/Discord/terminal-oriented threaded output renders `thinking` in italics.
- Core owns normalization; adapters own presentation.
- Session message APIs expose canonical block types (`text`, `thinking`, `pre_tool_use`, `tool_result`) without server-side filtering; clients/adapters decide what to render.

## Known caveats

- `send_result` and `send_file` require a valid `session_id` from `TMPDIR/teleclaude_session_id`.
- `escalate` is accepted only from a session running in a help desk; the recipients, the relay and the hand-back are `local/projects/teleclaude/spec/feature/agent_runtime/help-desk-escalation`.
