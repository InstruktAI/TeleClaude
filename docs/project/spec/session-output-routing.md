---
description: 'Canonical routing contract for session messages across origin UX and admin lanes.'
visibility: 'public'
---

# Session Output Routing — Spec

## What it is

This spec defines the routing contract for session messages across origin UX and admin visibility paths.

Core decides delivery scope and targeted recipients accordingly. Adapters decide how to present messages (threaded, edit-in-place, multi-placement) and how to route them internally (admin channels, origin UX, suppression).

Projection ordering, cursors, and origin gating are defined in `project/spec/session-projection`.
This spec owns recipient selection only.

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

| Scope         | Recipients                                           | Rule                                                                                                   |
| ------------- | ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| `ORIGIN_ONLY` | `origin_endpoint` only                               | Never fan out to non-origin admin destinations.                                                        |
| `ADMIN_ONLY`  | `admin_lane_destinations` only                       | Used for explicit admin reflection traffic.                                                            |
| `DUAL`        | `origin_endpoint` + Discord admin lane when eligible | Origin UI plus an admin copy on Discord when origin is not Discord, whatever role the session carries. |
| `CTRL`        | Internal control channels only                       | Not part of user/admin UI message fan-out; status controls may request throttled typing pulses.        |

### Message intent to scope mapping

| Message intent                       | Scope         | Notes                                                                                         |
| ------------------------------------ | ------------- | --------------------------------------------------------------------------------------------- |
| `feedback_notice_error_status`       | `ORIGIN_ONLY` | Includes notices, feedback prompts, and user-facing errors.                                   |
| `last_output_summary`                | `ORIGIN_ONLY` | Origin UX only, non-threaded/in-edit presentation only.                                       |
| `output_stream_chunk_final_threaded` | `DUAL`        | Includes incremental chunks, final output, and threaded blocks.                               |
| `input_reflection_text`              | `ADMIN_ONLY`  | Extra admin reflection goes to Discord only when origin is not Discord.                       |
| `input_reflection_voice`             | `ADMIN_ONLY`  | Same reflection lane policy as text input.                                                    |
| `input_reflection_mcp`               | `ADMIN_ONLY`  | Same reflection lane policy as text/voice input.                                              |
<!-- planned-change:quiet-reminders -->
| `reminder_lifecycle`                 | `DUAL`        | Typed reminder transitions use the existing origin plus Discord-admin recipient set.          |
<!-- change:quiet-reminders -->
<!-- /planned-change:quiet-reminders -->
| `ctrl_activity`                      | `CTRL`        | Activity control signals: turn start/end, tool events. Internal only; not visible UI content. |

### Reflection lane contract

Reflection is a UX observability feature, not a direct reply. Core creates only the extra admin reflection, and only for Discord.

- The normal origin-path delivery is separate and remains unchanged.
- When origin is not `discord`, core sends one extra reflection to Discord.
- When origin is `discord`, core does not create a duplicate reflection copy.
- Telegram is an origin/input adapter only and suppresses reflections instead of rendering them.
- Discord is the single admin adapter and renders reflected input for observability.
- Core still attaches source metadata (origin, actor identity) for Discord rendering.
- Origin continuity comes from normal reply delivery, not reflection echo.
- Discord reflection rendering is an actor-attributed contract: reflected user input must render with
  the resolved user display name and avatar when available, never as the agent/bot.
- If actor attribution cannot be resolved, or Discord webhook delivery cannot complete, the
  reflection lane fails or defers without posting the user text through the normal bot send path.
- Turn-boundary and typing-indicator delivery are presence/control mechanics only; they must not
  change reflection attribution or convert a user reflection into agent output.

For structured peer input, the reflection lane consumes cutter-derived
registered identity segments rather than an accepted-turn binding:

- Core retains one agent-facing bundle while Discord receives one ordered call
  per eligible segment.
- Every call carries cutter-derived header provenance, immutable event author,
  and original source session; a parsed peer source is accepted only when it is
  a live member of the active link.
- Presentation resolves relative to the viewing session. The owner renders as
  `<Identity>[ - <raw JobRole>]`; every remote author renders as
  `<Identity>[ - <raw JobRole>] (peer)`.
- Thinking mode remains structured provenance and never enters the Discord
  alias.
- The Discord adapter creates and edits through the resolved webhook identity,
  omits readable peer headers from copy, and retains a durable platform receipt
  per segment or output generation.
- Missing required identity fails visibly without bot fallback. An unresolved
  create is reconciled without blind resend and cannot freeze later output.

### Admin output lane contract

Assistant output follows a symmetric admin-copy rule so non-Discord-origin sessions stay observable in Discord.

<!-- planned-change:quiet-reminders -->
Typed reminder transitions reuse this lane's recipient resolution through the
`reminder_lifecycle` intent. Projection visibility decides whether a recipient
may see the reminder before routing runs. The mapping introduces no reminder
lane, priority, QoS class, or adapter-specific recipient rule.
<!-- change:quiet-reminders -->
<!-- /planned-change:quiet-reminders -->

- The origin UI adapter receives the session's direct live output.
- When origin is not `discord`, core additionally sends an admin copy of the same output to Discord.
- When origin is `discord`, core sends a single Discord delivery and does not duplicate.

- The session's role never gates the admin copy. Orchestrators, workers, integrators, and finalizers receive it on the same terms as any other session.

- Sessions with a non-UI origin (terminal, system, etc.) still get the admin copy when eligible, so agent output remains visible.
- The agent-stop transition is one durable write: the stop version, the payload belonging to it, the cleared summary, and a per-lane obligation (`final_output_due_at`) on every lane the routing policy resolves at that moment. Lanes not owed the turn have any prior obligation removed in the same write. Recipient selection happens here and nowhere else.
- The final projection for that stop delivers under the same version and records it as the delivery receipt (`last_delivered_at`). It is driven by the persisted obligations, not by current routing. It skips a lane whose receipt already covers the version; ordinary chunk passes keep their content-digest dedupe. The stop version is released once its pass reaches delivery, and retained by a pass that returns before that.
- Final-output repair (`reconcile_outstanding_final_outputs`) enumerates persisted obligations, never current routing, and targets a lane whose obligation is newer than its receipt. A legacy session carrying no obligation markers may repair only its provisioned origin lane, measured against `last_agent_stop_at`. A lane holding no obligation predates the record and is never enrolled retroactively, so widening the routing policy cannot conscript session history.
- Recovery runs as a single background pass once the request surface is listening, never inline in startup ahead of it. It carries no volume or rate budget.
- Channel provisioning for the admin copy is on-demand via the same path the reflection lane uses.
- Lifecycle status controls (`accepted`, `active`, `active_output`) may request throttled typing pulses on the origin and Discord admin lanes. These are platform presence signals, not message delivery, and must not render visible UI content.
- UI-origin input emits the existing `accepted` control at the input acceptance boundary (`deliver_inbound`), where all modalities converge, so the typing indicator appears promptly on input rather than only after the late `user_prompt_submit` hook. This reuses the lifecycle presence lane, stays throttled and scoped to the same origin/admin lane selection, and does not introduce a new `ctrl_activity` value for typing. Terminal-origin input retains the `user_prompt_submit` emission.
- Cache-backed remote session status dispatch uses existing origin metadata to request presence pulses. It must not provision local channels for cache-only remote sessions.

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

### Live routing origin and native turn provenance

`last_input_origin` remains a mutable live-routing summary used to choose a
session's direct-reply endpoint and to suppress an ordinary prompt already
visible on that adapter. It never classifies a historical transcript entry,
opens an output generation, or supplies peer provenance.

Runtime-qualified native entry identity names the turn. The shared envelope
cutter derives its ordered authored segments directly from registered framing
and ordinary gaps; peer and machine segments have no human UI surface and never
overwrite the live routing summary. Native terminal input uses the same entry
identity without an adapter receipt.

Acceptance may request presence but does not clear any adapter message or
cursor. Observing the genuine native user entry creates one next output
generation, and every adapter consumes that generation independently while
preserving segment order and presentation.

Canonical human UI surfaces remain `telegram`, `discord`, `whatsapp`, and
`web`; absence of a UI surface is distinct from any of those values.

### Projection ownership

Transcript/file truth is the sole source of conversational truth in v1. `session_ledger` blocks are the target source of truth in v2. The full projection contract lives in `project/spec/session-projection`.

| Field                  | Owner                | Purpose                                           |
| ---------------------- | -------------------- | ------------------------------------------------- |
| `last_projected_at`    | Transcript projector | Projection-owned watermark for replay/dedupe      |
| `last_message_sent`    | Transcript projector | Operational text snapshot of last projected input |
| `last_message_sent_at` | Transcript projector | Operational timestamp of last projected input     |

The projector uses `last_projected_at` for v1 dedupe decisions - it never reads `last_message_sent_at` for this purpose. Non-projector code (acceptance handlers, coordinators, UI adapters) must not advance `last_projected_at`. The projector writes `last_message_sent`/`last_message_sent_at` alongside `last_projected_at` for downstream operational consumers. Acceptance handlers may set these fields eagerly before the projector runs so that downstream consumers have immediate values; the projector's write is authoritative.

Projection crosses a user source entry once its runtime-qualified native entry
exists and segmentation completes from the entry itself. Projection never
substitutes mutable routing state for segment kind, authorship, or generation
identity.

### Actor attribution expectations

- Use adapter-provided display names when available.
- Fall back to stable adapter IDs when no display name is available.
- For MCP/AI-to-AI flows, use resolved AI actor identity (for example `AI Agent`), not raw transport internals.

## Allowed values

- `delivery_scope`: `ORIGIN_ONLY`, `ADMIN_ONLY`, `DUAL`, `CTRL`
- `cleanup_trigger`: `next_notice`, `next_turn`
<!-- planned-change:quiet-reminders -->
- `message_intent`: `feedback_notice_error_status`, `last_output_summary`, `output_stream_chunk_final_threaded`, `input_reflection_text`, `input_reflection_voice`, `input_reflection_mcp`, `reminder_lifecycle`, `ctrl_activity`
<!-- change:quiet-reminders -->
- `message_intent`: `feedback_notice_error_status`, `last_output_summary`, `output_stream_chunk_final_threaded`, `input_reflection_text`, `input_reflection_voice`, `input_reflection_mcp`, `ctrl_activity`
<!-- /planned-change:quiet-reminders -->

## Known caveats

- If an adapter has no provisioned channel for a session, delivery to that adapter is skipped.
- Telegram customer sessions are unprovisioned by design.
- Discord reflection webhook unavailability is not allowed to fall back to normal bot send. The
  reflection lane must fail, defer, or drop the
  reflection without rendering the user text as the agent/bot.
- Telegram does not render admin reflections.
- Admin-lane recipients can still render multiple internal placements. That is adapter behavior, not core routing policy.
- Command acknowledgements and lifecycle chatter are not cross-adapter broadcasts. Targeted origin delivery and Discord admin reflection are the only supported UI routing patterns.
- Status-derived typing pulses are not lifecycle chatter and not message broadcasts; they are throttled platform presence signals scoped to the same origin/admin adapter selection rules.

## See Also

- docs/project/spec/session-projection.md
