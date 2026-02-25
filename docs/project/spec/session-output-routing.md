---
id: 'project/spec/session-output-routing'
type: 'spec'
domain: 'software-development'
scope: 'project'
description: 'Canonical routing contract for session messages across origin UX and admin lanes.'
---

# Session Output Routing — Spec

## What this defines

This spec defines the routing contract for session messages across origin UX and admin visibility paths.

Core decides who should receive a message. Adapters decide how to present it (threaded, edit-in-place, multi-placement, etc.).

## Mental model: three lanes

1. **Origin UX lane**: direct user continuity (reply, notice, summary context).
2. **Dual output lane**: assistant operational output visible at origin and admin destinations.
3. **Reflection lane**: mirrored user/actor input visible to all non-source adapters for observability.

## Canonical fields

### Routing primitives

| Field                         | Meaning                                                                 |
| ----------------------------- | ----------------------------------------------------------------------- |
| `origin_endpoint`             | The single endpoint that receives direct user-facing replies.           |
| `admin_lane_destinations`     | Admin or observer destinations that mirror operational stream traffic.  |
| `delivery_scope`              | Recipient policy for a message: `ORIGIN_ONLY`, `DUAL`, or `CTRL`.       |
| `message_intent`              | Semantic category used to choose delivery scope.                        |
| `cleanup_trigger`             | Message lifetime policy only (deletion timing). Never recipient policy. |
| `reflection_actor_id`         | Stable actor identity used for reflection attribution.                  |
| `reflection_actor_name`       | Best-effort display name for reflection rendering.                      |
| `reflection_actor_avatar_url` | Optional avatar URL for adapter-specific rendering.                     |

### Delivery scopes

| Scope         | Recipients                                    | Rule                                            |
| ------------- | --------------------------------------------- | ----------------------------------------------- |
| `ORIGIN_ONLY` | `origin_endpoint` only                        | Never fan out to non-origin admin destinations. |
| `DUAL`        | `origin_endpoint` + `admin_lane_destinations` | Used for operational output flow.               |
| `CTRL`        | Internal control channels only                | Not part of user/admin UI fan-out.              |

### Message intent to scope mapping

| Message intent                       | Scope         | Notes                                                              |
| ------------------------------------ | ------------- | ------------------------------------------------------------------ |
| `feedback_notice_error_status`       | `ORIGIN_ONLY` | Includes notices, feedback prompts, and user-facing errors.        |
| `last_output_summary`                | `ORIGIN_ONLY` | Origin UX only, non-threaded/in-edit presentation only.            |
| `output_stream_chunk_final_threaded` | `DUAL`        | Includes incremental chunks, final output, and threaded blocks.    |
| `input_reflection_text`              | `DUAL`        | Implemented via reflection lane fan-out (all non-source adapters). |
| `input_reflection_voice`             | `DUAL`        | Same reflection lane policy as text input.                         |
| `input_reflection_mcp`               | `DUAL`        | Same reflection lane policy as text/voice input.                   |

## Reflection lane contract

Reflection is a UX observability feature, not a direct reply.

- Reflect to every provisioned UI adapter except the source adapter.
- Never suppress MCP reflections; they follow the same rule.
- Attribute reflected input to an actor (best effort name, optional avatar).
- Origin continuity comes from normal reply delivery, not reflection echo.

### Non-negotiable routing rules

- Recipient selection is based on `message_intent -> delivery_scope`.
- `origin_endpoint` is for direct reply continuity.
- `cleanup_trigger` controls deletion timing only. It never chooses recipients.
- Adapters own placement and rendering strategy.

### Channel provisioning

Channel provisioning still determines whether an adapter can receive delivery. Routing scope determines who should receive delivery.

| Session type | Fan-out targets                        |
| ------------ | -------------------------------------- |
| Admin/member | Telegram + Discord (all UI adapters)   |
| Customer     | Discord only (Telegram has no channel) |

### Entry point (`last_input_origin`)

`last_input_origin` records the most recent interaction source for session continuity. It supports direct replies to the origin endpoint.

### Actor attribution expectations

- Use adapter-provided display names when available.
- Fall back to stable adapter IDs when no display name is available.
- For MCP/AI-to-AI flows, use resolved AI actor identity (for example `AI Agent`), not raw transport internals.

## Allowed values

- `delivery_scope`: `ORIGIN_ONLY`, `DUAL`, `CTRL`
- `cleanup_trigger`: `next_notice`, `next_turn`
- `message_intent`: `feedback_notice_error_status`, `last_output_summary`, `output_stream_chunk_final_threaded`, `input_reflection_text`, `input_reflection_voice`, `input_reflection_mcp`

## Known caveats

- If an adapter has no provisioned channel for a session, delivery to that adapter is skipped.
- Telegram customer sessions are unprovisioned by design.
- Discord reflection webhook rendering is best-effort and falls back to normal bot send when unavailable.
- Admin-lane recipients can still render multiple internal placements. That is adapter behavior, not core routing policy.
