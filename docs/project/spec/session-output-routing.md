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

<!-- planned-change:reliable-authored-session-delivery -->

For peer cross-share input, "one extra reflection" means one ordered reflection
pass for the accepted source entry, not one Discord message containing the whole
entry:

- Core keeps the accepted peer bundle as one agent-facing input and one
  projection-watermark unit.
- The reflection pass decomposes that bundle into canonical source segments and
  calls the Discord admin lane once per segment, in source order.
- Each call carries the segment body plus its own `reflection_actor_name` and
  optional `reflection_actor_avatar_url`. Codex, Claude, and Gemini use their
  canonical aliases and stable agent avatars; human and machine-role segments
  keep their original display identity.
- The Discord adapter executes each call through the existing reflection
  webhook's per-message `username` and `avatar_url` overrides. It never posts a
  multi-author peer bundle through the bot-send path or exposes the canonical
  peer header as message copy.
- A missing optional human avatar may use the webhook's default avatar without
  changing the human alias. Missing required author identity fails the peer
  reflection instead of substituting the intermediary, target agent, or bot.

<!-- change:reliable-authored-session-delivery -->

For structured peer input, the reflection lane consumes the accepted turn's
durable segment carrier rather than message text:

- Core retains one agent-facing bundle while Discord receives one ordered call
  per eligible segment.
- Every call carries the stable turn, bundle, and segment identity plus immutable
  event author and original source session.
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

<!-- /planned-change:reliable-authored-session-delivery -->

### Admin output lane contract

Assistant output follows a symmetric admin-copy rule so non-Discord-origin sessions stay observable in Discord.

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

<!-- planned-change:reliable-authored-session-delivery -->

### Entry point (`last_input_origin`)

`last_input_origin` records the most recent accepted interaction source for session continuity. It supports direct replies to the origin endpoint and tells projection whether a user source entry was already visible in a UI client. It is live routing/presence metadata, not a durable audit log and not a projection cursor.

The field is set only at acceptance boundaries where normalized input becomes accepted core state. UI adapters pass origin metadata into the command layer; they do not mutate session state directly. Terminal input has no adapter acceptance boundary, so the terminal hook path records `terminal` at `user_prompt_submit`.

At the same UI input acceptance boundary, Core opens the UI output turn before
agent injection by asking the origin adapter and eligible Discord admin adapter
to clear delivery receipts and mark `turn_open_pending`, and emits the early
`accepted` presence signal that drives the typing pulse. When transcript
projection later exposes the accepted user boundary, adapters adopt that
timestamp as `turn_anchor_ts` and clear `turn_open_pending` without clearing the
new receipt again. Terminal input has no UI acceptance boundary and continues to
derive its turn start from the late `user_prompt_submit` hook.

Current canonical origins are `telegram`, `discord`, `whatsapp`, `web`, and `terminal`.
<!-- change:reliable-authored-session-delivery -->

### Live routing origin and bound turn provenance

`last_input_origin` remains a mutable live-routing summary used to choose a
session's direct-reply endpoint. It never classifies a historical transcript
entry, opens an output generation, decides reflection, or supplies peer
provenance.

Accepted-turn bindings carry runtime-qualified native entry identity and an
ordered composition of authored parts. Each receipt-backed part retains
orthogonal `turn_source`, human `ui_surface`, `accepted_at`, and event
authorship; surrounding local-human text remains its own part. UI-human input
may update the live routing summary after durable acceptance. Peer and machine
input have no human UI surface and never overwrite it. Native terminal input
binds from transcript truth without an adapter receipt. Rendered peer headers
and footers never define the composition.

Acceptance may request presence but does not clear any adapter message or
cursor. Binding the genuine composed transcript user entry creates one next
output generation, and every adapter consumes that generation independently
while preserving authored-part order and presentation.

Canonical human UI surfaces remain `telegram`, `discord`, `whatsapp`, and
`web`; absence of a UI surface is distinct from any of those values.
<!-- /planned-change:reliable-authored-session-delivery -->

### Projection ownership

Transcript/file truth is the sole source of conversational truth in v1. `session_ledger` blocks are the target source of truth in v2. The full projection contract lives in `project/spec/session-projection`.

| Field                  | Owner                | Purpose                                           |
| ---------------------- | -------------------- | ------------------------------------------------- |
| `last_projected_at`    | Transcript projector | Projection-owned watermark for replay/dedupe      |
| `last_message_sent`    | Transcript projector | Operational text snapshot of last projected input |
| `last_message_sent_at` | Transcript projector | Operational timestamp of last projected input     |

The projector uses `last_projected_at` for v1 dedupe decisions - it never reads `last_message_sent_at` for this purpose. Non-projector code (acceptance handlers, coordinators, UI adapters) must not advance `last_projected_at`. The projector writes `last_message_sent`/`last_message_sent_at` alongside `last_projected_at` for downstream operational consumers. Acceptance handlers may set these fields eagerly before the projector runs so that downstream consumers have immediate values; the projector's write is authoritative.

<!-- planned-change:reliable-authored-session-delivery -->

Projection must honor origin freshness before crossing a user source entry. If the next user entry's origin is not fresh, projection defers instead of guessing from stale routing state.
<!-- change:reliable-authored-session-delivery -->

Projection crosses a user source entry only after its accepted-turn binding is durable. An unbound post-cutover entry remains pending without advancing any consumer cursor; projection never substitutes mutable routing state for that binding.
<!-- /planned-change:reliable-authored-session-delivery -->

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
- Discord reflection webhook unavailability is not allowed to fall back to normal bot send. The
  reflection lane must fail, defer, or drop the
  reflection without rendering the user text as the agent/bot.
- Telegram does not render admin reflections.
- Admin-lane recipients can still render multiple internal placements. That is adapter behavior, not core routing policy.
- Command acknowledgements and lifecycle chatter are not cross-adapter broadcasts. Targeted origin delivery and Discord admin reflection are the only supported UI routing patterns.
- Status-derived typing pulses are not lifecycle chatter and not message broadcasts; they are throttled platform presence signals scoped to the same origin/admin adapter selection rules.

## See Also

- docs/project/spec/session-projection.md
