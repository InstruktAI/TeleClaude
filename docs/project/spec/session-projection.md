---
description: 'Canonical projection contract for reflecting session source truth into UI adapters.'
id: 'project/spec/session-projection'
scope: 'project'
type: 'spec'
visibility: 'public'
---

# Session Projection — Spec

## What it is

This spec defines how TeleClaude projects ordered session source truth into UI adapters.

Projection is not routing, polling, or adapter rendering. Routing decides recipients. Polling,
hooks, and origin writes wake projection. Adapters render, edit, split, and store delivery
receipts. Projection decides which source entries are eligible to be delivered next, in source
order, for each adapter lane.

In v1 the authoritative source is the agent transcript/source file plus the minimal session fields
needed to gate projection. In v2 the authoritative source is `session_ledger` blocks and cursors.
The invariant is the same in both versions: UI messages are a projection of source truth, never the
truth itself.

## Canonical fields

### Core concepts

| Field               | Meaning                                                                                                |
| ------------------- | ------------------------------------------------------------------------------------------------------ |
| `source_entry`      | One ordered user, assistant, system, or tool-derived block from the authoritative session source.      |
| `source_order`      | The order defined by the source file or ledger sequence. No adapter may reorder entries.               |
| `source_timestamp`  | Timestamp attached to a source entry, used only when sequence is not yet available.                    |
| `projection_cursor` | Monotonic per-adapter/per-lane cursor over source truth.                                               |
| `delivery_receipt`  | Adapter-local platform state such as message ids, char offsets, edit anchors, and overflow chunk ids.  |
| `activity_signal`   | A wakeup that says source state may have changed. It does not define content.                          |
| `origin_signal`     | The recorded origin for the current user turn. It gates projection across user turns.                  |
| `last_input_origin` | Live routing/presence signal for the most recently accepted user input. It is not a durable audit log. |

### Source truth

- Source order is absolute. Anything rendered to Discord, Telegram, web, or terminal-facing UI must
  follow the same order as the authoritative source entries.
- Adapter state is not source truth. Message ids, edit targets, char offsets, QoS queues, and
  threaded-output anchors are delivery receipts only.
- Projection may rebuild an adapter view from source truth plus that adapter's cursor. It must not
  require a remembered "current turn" inside the adapter to decide ordering.
- If a projection pass sees no eligible source entry after the cursor, it does nothing.

### Projection serialization

Projection is serialized per session across all entrypoints. Scheduled projection and poller-driven projection share the same per-session gate, and the gated section refreshes session state from the database before reading `last_projected_at` or `last_projected_output_digest`.

Scheduled projection still coalesces repeated wakeups: a signal that arrives while a scheduled pass is in flight marks one pending follow-up pass. The shared per-session gate prevents a scheduled pass and a direct poller pass from both reflecting the same user source entry before the projector-owned watermark advances.

### Cursor model

- Each adapter lane has its own projection cursor.
- A cursor advances only after the adapter handoff for the corresponding source span succeeds.
- A failed platform send/edit leaves the cursor unchanged so a later projection pass can retry from
  the same source position.
- Overflow splitting can create multiple platform messages for one source span. Those platform
  messages remain one logical projected span for cursor advancement.
- Re-rendering an already delivered source span is a repair/retry concern and must be idempotent by
  source span, not by current adapter message placement.
- Projection execution is serialized per session. If a scheduled projection pass and a poller-driven
  projection pass wake at the same time, only one pass may inspect and update the user-entry
  watermark at a time. Additional wakeups coalesce into a follow-up pass, and each pass refreshes
  session state before checking `last_projected_at` or the output projection digest.

### Origin gate

Projection must not pass a new user source entry until that entry's origin has been recorded.

- `last_input_origin` is set at the acceptance boundary where normalized user input becomes accepted
  core state.
- UI-origin input records the adapter-provided origin at the successful accepted-input boundary,
  before typing callbacks, queue workers, or projection-visible wakeups can observe stale origin
  metadata.
- Terminal-origin input records `terminal` from the `user_prompt_submit` boundary, because terminal
  input bypasses the inbound adapter queue.
- A stale origin from a previous turn cannot satisfy the gate for a later user source entry.
- In v1, freshness is established with the accepted input timestamp/session metadata available near
  `last_message_sent_at` and the transcript user timestamp. In v2, freshness belongs to the ledger
  block metadata and cursor transaction.
- If source activity is observed before the matching origin is fresh, projection defers and leaves
  the cursor unchanged.

### User entry delivery

The first visible user entry after a cursor is handled according to its origin.

- If the user entry originated from the same UI adapter that is being projected to, that user entry
  is already visible in that client. Projection marks/skips it for that adapter and must not echo it
  back.
- If the user entry originated from another UI adapter, the admin/reflection lane may project it
  according to `project/spec/session-output-routing`.
- If the user entry originated from `terminal`, UI adapters must project it, because the user did not
  already see that input in those clients.
- Assistant output following a user entry is projected normally after the origin gate is satisfied.

### Signals

Signals wake projection. They do not decide projection content.

- `inbound_accepted`: UI-origin input was accepted into core state.
- `user_prompt_submit`: the agent runtime observed a submitted user prompt in the native hook stream.
- `terminal_origin_recorded`: terminal origin was recorded for a terminal user turn.
- `tmux_output_changed`: terminal output changed and transcript/source state may have advanced.
- `tool_use`: agent activity indicates an active turn.
- `agent_stop`: turn completion may make final output/title/replay work eligible.
- `native_metadata_update`: native session metadata or transcript path may have landed.
- `native_session_refresh`: native session identity may have changed or become discoverable.
- `daemon_startup_reconcile`: restart recovery should replay from cursors.

Only `terminal_origin_recorded` is an origin write that also acts as a projection signal. Non-terminal
origin writes are not standalone projection signals: `inbound_accepted` is emitted or scheduled only
after accepted-input metadata is durable and fresh; later activity signals may also wake projection.
The later `user_prompt_submit` hook may wake projection even when it preserves already-fresh UI-origin
metadata. Origin writes and hook signals do not decide content; the projection gate still reads
transcript/source truth and defers when the matching origin is not fresh.

### Adapter delivery mechanics

Adapters own platform mechanics only:

- edit-in-place versus append,
- message splitting and overflow continuation,
- markdown/platform formatting,
- rate limiting and QoS coalescing,
- delivery receipt storage,
- cleanup of platform messages.

Adapters do not own:

- source ordering,
- turn boundary truth,
- projection cursor advancement,
- duplicate suppression across source entries,
- origin freshness.

`break_threaded_turn` is not a projection primitive. It may drop pending QoS payloads as a delivery
cleanup, but it must not be used to decide what source content has or has not been projected.

## Allowed values

Canonical origins:

- `telegram`
- `discord`
- `whatsapp`
- `web`
- `terminal`

Projection outcomes:

- `delivered` - source span was handed off and cursor advanced.
- `skipped_already_visible` - source span was already visible in the origin adapter and cursor advanced.
- `deferred_missing_origin` - source advanced but the matching origin was not fresh yet.
- `failed_retryable` - adapter handoff failed and cursor did not advance.

Signal types:

- `inbound_accepted`
- `user_prompt_submit`
- `terminal_origin_recorded`
- `tmux_output_changed`
- `tool_use`
- `agent_stop`
- `native_metadata_update`
- `native_session_refresh`
- `daemon_startup_reconcile`

## Known caveats

- v1 still stores projection-related state across session columns and adapter metadata. New code must
  reduce that split, not add more adapter-owned truth.
- Timestamps are a v1 compromise. Sequence-based ledger cursors are the v2 target.
- Platform overflow can produce multiple Discord or Telegram messages for one source span. That is
  not duplicate transcript data and must be represented as one logical projection.
- Agent transcripts can lag behind a signal. A projection pass with missing source content or missing
  fresh origin should defer without advancing cursors.

## See Also

- docs/project/spec/session-output-routing.md
- docs/project/spec/inbound-queue.md
- docs/project/design/architecture/output-polling.md
- docs/project/design/architecture/conversation-delivery.md
- docs/project/design/architecture-v2/services.md
