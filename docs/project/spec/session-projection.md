---
description: 'Canonical projection contract for reflecting session source truth into UI adapters.'
visibility: 'public'
---

# Session Projection — Spec

## What it is

This spec defines how TeleClaude projects ordered session source truth into UI adapters.

Projection is not routing, polling, or adapter rendering. Routing decides recipients. Polling,
hooks, and origin writes wake projection. Adapters render, edit, split, and store delivery
receipts. Projection decides which source entries are eligible to be delivered next, in source
order, for each adapter lane.

The authoritative source for human-facing projection is the agent transcript/source file plus the
minimal session fields and per-consumer native-output cursors needed to gate projection. Typed
reminder records remain service-owned inspection data rather than human-facing projection input.
UI messages are a projection of source truth, never the truth itself.

## Canonical fields

### Core concepts

| Field              | Meaning                                                                                           |
| ------------------ | ------------------------------------------------------------------------------------------------- |
| `source_entry`     | One ordered user, assistant, system, or tool-derived block from the authoritative session source. |
| `source_order`     | The order defined by the source file or ledger sequence. No adapter may reorder entries.          |
| `source_timestamp` | Timestamp attached to a source entry, used only when sequence is not yet available.               |

| `projection_cursor` | Monotonic per-adapter/per-lane cursor over source truth. |
| `delivery_receipt` | Adapter-local platform state such as message ids, char offsets, edit anchors, and overflow chunk ids. |
| `activity_signal` | A wakeup that says source state may have changed. It does not define content. |
| `origin_signal` | The recorded origin for the current user turn. It gates projection across user turns. |
| `last_input_origin` | Live routing/presence signal for the most recently accepted user input. It is not a durable audit log. |
| `accepted_input_fingerprint` | A fixed-length prefix of the accepted turn, written at every acceptance point and read only to compare one turn against the last. It is never rendered: the prefix cuts mid-entry and severs envelope closures, so it cannot be classified. |
| `visible_input_span` | What a person sent in one turn, resolved from the turn as written at the moment it is accepted and rendered on the session row. An envelope contributes its body, never its framing; a turn that is wholly platform text — a notification, a wake, a checkpoint — contributes nothing and the row shows no input. Recognition is by declared closure, so a person's own bracketed words stay their words. |
| `output_visibility_policy` | Per-recipient policy that decides which non-conversational source categories are eligible for projection before adapter rendering. |
| `projection_surface` | Destination family used by visibility policy: `mobile` for chat adapters, `web` for browser/API projection, and `tui` for the raw terminal pane. |

Per-person category overrides accept `off`, `mobile`, `web`, `both`, or
`null`. `off` hides the category on every projected surface. `null` inherits
the recipient role default.

### Source truth

- Source order is absolute. Anything rendered to Discord, Telegram, web, or terminal-facing UI must
  follow the same order as the authoritative source entries.
- Adapter state is not source truth. Message ids, edit targets, char offsets, QoS queues, and
  threaded-output anchors are delivery receipts only.
- Projection may rebuild an adapter view from source truth plus that adapter's cursor. It must not
  require a remembered "current turn" inside the adapter to decide ordering.
- If a projection pass sees no eligible source entry after the cursor, it does nothing.

Reminder lifecycle records are typed service-owned inspection data, not parsed
copies of CLI tool results or agent envelopes and not a second human-facing
projection stream. Their monotonic `reminder_entry_id` defines source order for
reminder queries and agent session-tail inspection. Native transcript projection
and its cursors remain independent of that inspection stream.

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

### Envelope-authoritative segmentation gate

Projection classifies a native user entry directly from its registered envelope
boundaries and the ordinary gaps around them. Classification is complete when
the entry exists and never waits on receipt correlation.

- Every complete registered envelope contributes one typed authored segment;
  every span outside those envelopes is local prompt input.
- Only the registered opening and its declared closure are parsed. Bodies are
  opaque and never compared, scanned, or correlated to queue content.
- Assistant entries remain agent output and are not cut as user input.
- Runtime-qualified native entry identity is the durable turn and generation
  key. Repeated projection and restart derive the same segmentation from the
  same entry.
- Peer and machine segments carry no human UI surface and never overwrite
  human-origin routing state. The mutable origin summary may select
  same-adapter suppression for ordinary prompt input only; it never changes a
  segment's kind or author.

### User entry and output-generation delivery

Every native user entry is handled independently by each eligible consumer,
while its cut segments retain their individual reflection and presentation
facts.

- The adapter matching an ordinary prompt's current UI origin skips that
  already-visible segment without changing its kind or author.
- Other eligible admin/reflection lanes render each visible segment according
  to routing policy and native-entry order.
- Peer and machine segments reflect from their registered header identity, not
  from a human-origin value inherited from another session.
- One runtime-qualified native user entry creates one next output generation.
  Input acceptance itself never clears the current generation.
- Assistant spans carry that native generation identity and can update only
  that generation, so late older-turn output cannot edit or duplicate the next
  turn.

### Signals

Signals wake projection. They do not decide projection content.

- `inbound_accepted`: UI-origin input was accepted into core state.
- `user_prompt_submit`: the agent runtime observed a submitted user prompt in the native hook stream.
- `terminal_origin_recorded`: terminal origin was recorded for a terminal user turn.
- `tmux_output_changed`: terminal output changed and transcript/source state may have advanced.
- `pre_tool_use`: agent activity indicates an active turn.
- `agent_stop`: turn completion may make final output/title/replay work eligible.
- `native_metadata_update`: native session metadata or transcript path may have landed.
- `native_session_refresh`: native session identity may have changed or become discoverable.
- `daemon_startup_reconcile`: restart recovery should replay from cursors.

`inbound_accepted` signals that a durable queue row exists; it does not itself cut an output generation.
`terminal_origin_recorded` wakes projection for native terminal input that has no adapter receipt.
Later activity signals may repeat freely. Signals never decide content or authorship: the bound native
turn and each consumer's durable cursor remain authoritative, and an unbound post-cutover entry defers.

### Adapter delivery mechanics

Adapters own platform mechanics only:

- edit-in-place versus append,
- message splitting and overflow continuation,
- markdown/platform formatting,
- rate limiting and QoS coalescing,
- delivery receipt storage,
- cleanup of platform messages.

Every core-to-adapter delivery declares the body's authoring format. The common
adapter handoff dispatches that format before platform splitting or sending:

plain text is rendered literally, Markdown passes through the adapter's
Markdown renderer exactly once, and HTML uses the adapter's supported HTML
mechanics or a readable plain-text degradation. Own-session output, peer and
caller-origin reflections, voice transcriptions, and overflow continuations
use this same format-aware path.

Content provenance never selects adapter mechanics. A voice transcription is
ordinary plain text; it does not cause core to choose a separate overflow API,
and adapters do not branch on transcription provenance. Core chooses the
recipient and declares the content format. The adapter alone owns platform
encoding, safe splitting, continuation state, and send/edit operations.

Adapters do not own:

- source ordering,
- turn boundary truth,
- projection cursor advancement,
- duplicate suppression across source entries,
- origin freshness.

Discarding queued platform payloads is delivery cleanup and never a projection decision. Input
acceptance discards nothing: an accepted input leaves every pending payload, message id, character
offset, and cursor intact for the generation still in flight.

Structured peer entries carry an additional Discord presentation contract:

- Segment boundaries, source identity, author identity, ordering, and loop-prevention facts come from the durable structured carrier.
- Readable peer opening headers and closing footers are omitted from Discord copy and are never parsed by projection.
- Each eligible segment becomes one ordered webhook message containing only its body.
- Presentation resolves relative to the viewing session as `<Identity>[ - <raw JobRole>][ (peer)]`; thinking mode never appears in the alias.
- The owner lacks `(peer)` and every author from another session receives it, including humans and role-bearing machine authors.
- Each adapter generation and reflected segment keeps its own durable platform receipt. A failure or unresolved create cannot roll back transcript acceptance or another consumer cursor.
- Structured, body-free logs at policy-defined levels record every resolution, create, edit, reconciliation, omission, and completion decision with full identifiers.

### Output visibility policy

Projection applies per-recipient output visibility before adapter rendering. Adapters
receive only source categories that the projection policy marks eligible for that
recipient and surface; adapters must not re-implement role, category, or tool visibility
decisions.

Per-person preferences control two configurable categories:

- `system_messages` — orchestrator, integrator, finalizer, worker, and other system coordination messages.
- `tool_calls` — tool invocation blocks, never tool result bodies.

Defaults are role-sensitive: admins see `system_messages` and `tool_calls` on mobile
and web unless their per-person config says otherwise; members, contributors, and
newcomers see neither by default.

Some source categories are not configurable. Tool result bodies are TUI-only.
Checkpoint messages and agent-CLI side-channel artifacts are dropped from every
projected surface. Control headers — `[TeleClaude Notification]`, `[TeleClaude Input
Request]`, `[TeleClaude Checkpoint]` — are never projected to a human surface under
any per-person setting; `project/spec/message-headers` governs their vocabulary and
this policy is unconditional, not a default that a preference can override. Peer
cross-share content remains visible on every projected surface because it is
conversational substance, not infrastructure chatter. The TUI continues to show the
raw pane unchanged and does not consume projection filtering.

A turn-complete output consisting solely of the sentinel `NOOP` is a no-op turn:
it is dropped from every projected surface and from notification delivery,
unconditionally. The sentinel is how an agent whose runtime cannot end a turn
silently closes a turn that warrants no output, so suppression is structural —
never a preference, and never conversational substance. The raw transcript
retains the turn.

### Reminder lifecycle visibility

Every material reminder transition is an ordered typed record in the owning
session's reminder-entry stream: armed, replaced, cancelled, and the firing
itself. A false activation predicate creates no transition and therefore no
entry. Reminder queries and the agent session-tail surface render these typed
records through the agent-facing reminder envelope in source order.

Only a firing crosses the control-delivery contract into the owning agent
session. Human-facing projection has no reminder cursor, reminder delivery
intent, recipient resolution, adapter handoff, or reminder formatter.
Subsequent agent-authored output remains outside reminder projection; a
satisfied firing remains silent under the `NOOP` contract.

Control-delivery acceptance carries the firing's structured classification.
The native envelope is presentation for the receiving agent, never the source
from which projection recovers reminder identity, lifecycle state, or delivery
eligibility. A reminder-shaped native envelope is excluded from human surfaces
fail-closed; rendered grammar grants no reminder identity or lifecycle authority.

## Allowed values

Input delivery origins:

- `telegram`
- `discord`
- `whatsapp`
- `web`
- `terminal`

Human UI origin surfaces remain `telegram`, `discord`, `whatsapp`, and `web`.
`terminal` carries no human UI surface. Reminder firings use control delivery
and are not input origins.

Projection surfaces:

- `mobile`
- `web`
- `both`
- `tui`

Per-person visibility setting values:

- `null` - use the role-based default.
- `mobile` - show the category only on mobile/chat adapters.
- `web` - show the category only on web/API projection.
- `both` - show the category on both mobile/chat adapters and web/API projection.

Projection outcomes:

- `delivered` - source span was handed off and cursor advanced.
- `skipped_already_visible` - source span was already visible in the origin adapter and cursor advanced.

- `failed_retryable` - adapter handoff failed and cursor did not advance.

Signal types:

- `inbound_accepted`
- `user_prompt_submit`
- `terminal_origin_recorded`
- `tmux_output_changed`
- `pre_tool_use`
- `agent_stop`
- `native_metadata_update`
- `native_session_refresh`
- `daemon_startup_reconcile`

## Known caveats

- v1 still stores projection-related state across session columns and adapter metadata. New code must
  reduce that split, not add more adapter-owned truth.

- Native transcripts can lag an acceptance signal. An unbound post-cutover entry remains observable and fail-closed until durable receipt-to-turn reconciliation completes.

- Platform overflow can produce multiple Discord or Telegram messages for one source span. That is
  not duplicate transcript data and must be represented as one logical projection.

- Agent transcripts can lag behind a signal. A projection pass with missing source content or an unbound post-cutover turn defers without advancing any consumer cursor.

## See Also

- docs/project/spec/session-output-routing.md
- docs/project/spec/inbound-queue.md
- docs/project/spec/message-headers.md — the control-header vocabulary this spec's unconditional never-projected rule derives from.
- docs/project/design/architecture/output-polling.md
- docs/project/design/architecture/conversation-delivery.md
