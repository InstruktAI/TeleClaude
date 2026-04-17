---
id: 'project/spec/session-output-routing'
type: 'spec'
domain: 'software-development'
scope: 'project'
description: 'Canonical routing contract for session messages across origin UX and admin lanes.'
---

# Session Output Routing — Spec

## What it is

This spec defines the routing contract for session messages across origin UX and admin visibility paths.

Core decides delivery scope and targeted recipients accordingly. Adapters decide how to present messages (threaded, edit-in-place, multi-placement) and how to route them internally (admin channels, origin UX, suppression).

### Mental model: three lanes

1. **Origin UX lane**: direct user continuity (reply, notice, summary context).
2. **Live output lane**: assistant operational output routed to the origin UI endpoint plus an admin copy on Discord when eligible.
3. **Reflection lane**: mirrored user/actor input sent only to the Discord admin adapter when the origin is not Discord. The normal origin-path delivery remains separate.

## Canonical fields

### Routing primitives

| Field                         | Meaning                                                                 |
| ----------------------------- | ----------------------------------------------------------------------- |
| `origin_endpoint`             | The single endpoint that receives direct user-facing replies.           |
| `admin_lane_destinations`     | Admin or observer destinations that receive explicit admin copies.      |
| `delivery_scope`              | Recipient policy: `ORIGIN_ONLY`, `ADMIN_ONLY`, `DUAL`, or `CTRL`.       |
| `message_intent`              | Semantic category used to choose delivery scope.                        |
| `cleanup_trigger`             | Message lifetime policy only (deletion timing). Never recipient policy. |
| `reflection_actor_id`         | Stable actor identity used for reflection attribution.                  |
| `reflection_actor_name`       | Best-effort display name for reflection rendering.                      |
| `reflection_actor_avatar_url` | Optional avatar URL for adapter-specific rendering.                     |

### Delivery scopes

| Scope         | Recipients                                           | Rule                                                                                               |
| ------------- | ---------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `ORIGIN_ONLY` | `origin_endpoint` only                               | Never fan out to non-origin admin destinations.                                                    |
| `ADMIN_ONLY`  | `admin_lane_destinations` only                       | Used for explicit admin reflection traffic.                                                        |
| `DUAL`        | `origin_endpoint` + Discord admin lane when eligible | Origin UI plus an admin copy on Discord when origin is not Discord and session is not system-role. |
| `CTRL`        | Internal control channels only                       | Not part of user/admin UI fan-out.                                                                 |

### Message intent to scope mapping

| Message intent                       | Scope         | Notes                                                                                 |
| ------------------------------------ | ------------- | ------------------------------------------------------------------------------------- |
| `feedback_notice_error_status`       | `ORIGIN_ONLY` | Includes notices, feedback prompts, and user-facing errors.                           |
| `last_output_summary`                | `ORIGIN_ONLY` | Origin UX only, non-threaded/in-edit presentation only.                               |
| `output_stream_chunk_final_threaded` | `DUAL`        | Includes incremental chunks, final output, and threaded blocks.                       |
| `input_reflection_text`              | `ADMIN_ONLY`  | Extra admin reflection goes to Discord only when origin is not Discord.               |
| `input_reflection_voice`             | `ADMIN_ONLY`  | Same reflection lane policy as text input.                                            |
| `input_reflection_mcp`               | `ADMIN_ONLY`  | Same reflection lane policy as text/voice input.                                      |
| `ctrl_activity`                      | `CTRL`        | Activity control signals: turn start/end, tool events. Internal only; not UI content. |

### Reflection lane contract

Reflection is a UX observability feature, not a direct reply. Core creates only the extra admin reflection, and only for Discord.

- The normal origin-path delivery is separate and remains unchanged.
- When origin is not `discord`, core sends one extra reflection to Discord.
- When origin is `discord`, core does not create a duplicate reflection copy.
- Telegram is an origin/input adapter only and suppresses reflections instead of rendering them.
- Discord is the single admin adapter and renders reflected input for observability.
- Core still attaches source metadata (origin, actor identity) for Discord rendering.
- Origin continuity comes from normal reply delivery, not reflection echo.

### Admin output lane contract

Assistant output follows a symmetric admin-copy rule so non-Discord-origin sessions stay observable in Discord.

- The origin UI adapter receives the session's direct live output.
- When origin is not `discord`, core additionally sends an admin copy of the same output to Discord.
- When origin is `discord`, core sends a single Discord delivery and does not duplicate.
- System-role sessions (integrator, finalizer, worker, etc.) skip the admin copy to avoid infrastructure noise.
- Sessions with a non-UI origin (terminal, system, etc.) still get the admin copy when eligible, so agent output remains visible.
- Final-output repair (`reconcile_outstanding_final_outputs`) follows the same dual-lane rule when repairing persisted output.
- Channel provisioning for the admin copy is on-demand via the same path the reflection lane uses.

#### Non-negotiable routing rules

- Recipient selection is based on `message_intent -> delivery_scope`.
- `origin_endpoint` is for direct reply continuity.
- `cleanup_trigger` controls deletion timing only. It never chooses recipients.
- Adapters own placement and rendering strategy.

### Channel provisioning

Channel provisioning determines whether a UI adapter can receive delivery. It does not expand routing scope, and transport metadata is not part of the UI origin model.

- Live output and final-output repair target the origin UI adapter plus the Discord admin lane when eligible.
- Discord admin reflection is the extra admin UI lane for user input, paired with the admin output lane for assistant output.
- Transport metadata such as Redis `target_computer` is not a session origin and does not participate in UI routing.

### Entry point (`last_input_origin`)

`last_input_origin` records the most recent interaction source for session continuity. It supports direct replies to the origin endpoint. It is routing metadata set only at acceptance boundaries — where normalized input becomes accepted core state. UI adapters must not write this field.

Current canonical origins are `telegram`, `discord`, `whatsapp`, `web`, and `terminal`.

### Projection ownership

Transcript/file truth is the sole source of conversational truth. One projector owns user-input and agent-output projection into canonical state.

| Field                  | Owner                | Purpose                                           |
| ---------------------- | -------------------- | ------------------------------------------------- |
| `last_projected_at`    | Transcript projector | Projection-owned watermark for replay/dedupe      |
| `last_message_sent`    | Transcript projector | Operational text snapshot of last projected input |
| `last_message_sent_at` | Transcript projector | Operational timestamp of last projected input     |

The projector uses `last_projected_at` for dedupe decisions — it never reads `last_message_sent_at` for this purpose. Non-projector code (acceptance handlers, coordinators, UI adapters) must not advance `last_projected_at`. The projector writes `last_message_sent`/`last_message_sent_at` alongside `last_projected_at` for downstream operational consumers. Acceptance handlers may set these fields eagerly before the projector runs so that downstream consumers have immediate values; the projector's write is authoritative.

### Actor attribution expectations

- Use adapter-provided display names when available.
- Fall back to stable adapter IDs when no display name is available.
- For MCP/AI-to-AI flows, use resolved AI actor identity (for example `AI Agent`), not raw transport internals.

## Allowed values

- `delivery_scope`: `ORIGIN_ONLY`, `ADMIN_ONLY`, `DUAL`, `CTRL`
- `cleanup_trigger`: `next_notice`, `next_turn`
- `message_intent`: `feedback_notice_error_status`, `last_output_summary`, `output_stream_chunk_final_threaded`, `input_reflection_text`, `input_reflection_voice`, `input_reflection_mcp`, `ctrl_activity`

## Known caveats

- If an adapter has no provisioned channel for a session, delivery to that adapter is skipped.
- Telegram customer sessions are unprovisioned by design.
- Discord reflection webhook rendering is best-effort and falls back to normal bot send when unavailable.
- Telegram does not render admin reflections.
- Admin-lane recipients can still render multiple internal placements. That is adapter behavior, not core routing policy.
- Command acknowledgements and lifecycle chatter are not cross-adapter broadcasts. Targeted origin delivery and Discord admin reflection are the only supported UI routing patterns.
