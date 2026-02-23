---
id: 'project/spec/session-output-routing'
type: 'spec'
domain: 'software-development'
scope: 'project'
description: 'Routing rules for session output across UI adapters (Telegram, Discord).'
---

# Session Output Routing — Spec

## What it is

Defines how session output is routed to UI adapters. These rules govern channel provisioning (which adapter gets a channel for a session) and output fan-out (which adapters receive output updates).

## Canonical fields

### Roles

| Role     | Description                             |
| -------- | --------------------------------------- |
| admin    | Project operator with full access       |
| member   | Team member with project access         |
| customer | External user interacting via Help Desk |

### Adapter purposes

| Adapter  | Purpose                                           |
| -------- | ------------------------------------------------- |
| Telegram | Admin/member cockpit for project development      |
| Discord  | Full platform: admin sessions + customer sessions |

### Channel provisioning

Every session gets channels provisioned via `ensure_ui_channels()`. Each adapter decides whether to provision based on session type:

| Session type            | Telegram            | Discord                              |
| ----------------------- | ------------------- | ------------------------------------ |
| Admin/member            | Topic in supergroup | Thread in project forum (or Unknown) |
| Customer (`human_role`) | **Skipped**         | Thread in Help Desk forum            |

Customer detection is based solely on `session.human_role == "customer"`. The entry point (`last_input_origin`) does not influence routing decisions.

### Output fan-out

Output updates fan out to **all** UI adapters that have a provisioned channel for the session:

| Session type | Fan-out targets                        |
| ------------ | -------------------------------------- |
| Admin/member | Telegram + Discord (all UI adapters)   |
| Customer     | Discord only (Telegram has no channel) |

Fan-out is unconditional. Channel provisioning determines which adapters participate — not the routing layer.

### Entry point (`last_input_origin`)

`last_input_origin` records which entry point initiated or last interacted with a session. Entry points include UI adapters (Telegram, Discord), MCP, API, and hooks — it is not adapter-specific.

Its only function is:

- Identifying which adapter has the "interactive" channel (for inline keyboards, footers, etc.)
- Providing a return path for direct responses

It is never used to decide:

- Whether to provision a channel
- Whether to fan out output
- Whether a session is customer-facing

### Discord forum routing

Discord routes sessions to forums based on role:

| `human_role`              | Discord forum                       |
| ------------------------- | ----------------------------------- |
| `"customer"`              | Customer Sessions                   |
| anything else (or `None`) | Matched project forum, or "Unknown" |

### Threaded output

Threaded output (incremental markdown rendering) is enabled per-session:

- When the `threaded_output` experiment flag is enabled for the session's agent
- When standard output suppression is active (`send_output_update` returns early)

Both standard and threaded output paths fan out to all provisioned adapters.

## Known caveats

- Telegram does not support customer sessions. If a customer session is somehow routed to Telegram, `ensure_channel` must return the session unchanged (no topic created).
- Channel provisioning is idempotent. If a channel already exists, `ensure_channel` is a no-op.
- When `all_sessions_channel_id` or `help_desk_channel_id` is None (infrastructure not yet provisioned), Discord's `ensure_channel` silently skips — no error, no channel.
