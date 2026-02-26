---
id: project/spec/tools/escalation
type: spec
scope: project
description: Tool contract for telec sessions escalate.
audience: [admin, help-desk]
---

# Escalation Tool — Spec

## What it is

The `telec sessions escalate` MCP tool creates a Discord relay thread for admin-to-customer communication and activates relay mode on the calling session.

## Canonical fields

**Tool name:** `telec sessions escalate`

**Parameters:**

| Parameter         | Type   | Required | Description                                     |
| ----------------- | ------ | -------- | ----------------------------------------------- |
| `customer_name`   | string | yes      | Customer name, used as the Discord thread title |
| `reason`          | string | yes      | Why the AI is escalating                        |
| `context_summary` | string | no       | Brief summary of the conversation so far        |

**Return value:** Confirmation string with the relay thread ID, or an error message.

**Behavior:**

1. Creates a thread in the Discord escalation forum channel.
2. Posts the reason and context summary as the opening message.
3. Sets `relay_status = "active"` on the session.
4. Stores `relay_discord_channel_id` and `relay_started_at` on the session.
5. Sends a notification to subscribed admins.
6. Returns confirmation to the calling agent.

**Role gating:** Only available in sessions with `human_role: customer`. Excluded from worker, member, and unauthorized role tiers.

## Known caveats

- Requires Discord adapter to be running and `escalation_channel_id` to be configured.
- If Discord is unavailable, the tool returns an error. The agent must handle this gracefully.
- Multiple escalations within one session create separate relay threads. Each `@agent` handback clears the relay state.
