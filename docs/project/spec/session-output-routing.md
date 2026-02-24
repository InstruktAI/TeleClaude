---
id: 'project/spec/session-output-routing'
type: 'spec'
domain: 'software-development'
scope: 'project'
description: 'Canonical routing contract for session messages across origin UX and admin lanes.'
---

# Session Output Routing — Spec

## What it is

This spec defines one clear routing contract for session messages.

Core decides message intent and delivery scope. Adapters decide how to present delivered messages (edit-in-place, threaded, multi-placement, etc.).

## Canonical fields

### Routing primitives

| Field                     | Meaning                                                                 |
| ------------------------- | ----------------------------------------------------------------------- |
| `origin_endpoint`         | The single endpoint that receives direct user-facing replies.           |
| `admin_lane_destinations` | Admin or observer destinations that mirror operational stream traffic.  |
| `delivery_scope`          | Recipient policy for a message: `ORIGIN_ONLY`, `DUAL`, or `CTRL`.       |
| `message_intent`          | Semantic category used to choose delivery scope.                        |
| `cleanup_trigger`         | Message lifetime policy only (deletion timing). Never recipient policy. |

### Delivery scopes

| Scope         | Recipients                                    | Rule                                            |
| ------------- | --------------------------------------------- | ----------------------------------------------- |
| `ORIGIN_ONLY` | `origin_endpoint` only                        | Never fan out to non-origin admin destinations. |
| `DUAL`        | `origin_endpoint` + `admin_lane_destinations` | Used for operational output flow.               |
| `CTRL`        | Internal control channels only                | Not part of user/admin UI fan-out.              |

### Message intent to scope mapping

| Message intent                       | Scope         | Notes                                                            |
| ------------------------------------ | ------------- | ---------------------------------------------------------------- |
| `feedback_notice_error_status`       | `ORIGIN_ONLY` | Includes notices, feedback prompts, and user-facing errors.      |
| `last_output_summary`                | `ORIGIN_ONLY` | Origin UX only. Non-threaded adapters only (in-edit path).       |
| `output_stream_chunk_final_threaded` | `DUAL`        | Includes incremental chunks, final output, and threaded blocks.  |
| `input_reflection_text`              | `DUAL`        | Reflected across endpoints per adapter policy (source excluded). |
| `input_reflection_voice`             | `DUAL`        | Same reflection policy as text input.                            |
| `input_reflection_mcp`               | `CTRL`        | Reflection to user/admin UI is suppressed.                       |

### Non-negotiable routing rules

- Recipient selection is based on `message_intent -> delivery_scope`.
- `origin_endpoint` is for direct reply continuity. It is not fan-out policy.
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

## Allowed values

- `delivery_scope`: `ORIGIN_ONLY`, `DUAL`, `CTRL`
- `cleanup_trigger`: `next_notice`, `next_turn`
- `message_intent`: `feedback_notice_error_status`, `last_output_summary`, `output_stream_chunk_final_threaded`, `input_reflection_text`, `input_reflection_voice`, `input_reflection_mcp`

## Known caveats

- If an adapter has no provisioned channel for a session, delivery to that adapter is skipped.
- Telegram customer sessions are unprovisioned by design.
- Admin-lane recipients can still render multiple internal placements. That is adapter behavior, not core routing policy.
