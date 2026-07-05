---
description: 'UI adapters translate human inputs into events and render outputs with UX rules.'
visibility: 'public'
---

# Ui Adapter — Design

## Required reads

- @docs/project/policy/ux-message-cleanup.md
- @docs/project/spec/session-output-routing.md
- @docs/project/spec/session-projection.md

## Purpose

Responsibilities

- Normalize user commands and messages into daemon events.
- Render session output and feedback according to UX cleanup rules.

<!-- planned-change:adapter-channel-lifecycle-relocation -->

- Manage topics or channels for per-session organization.

<!-- change:adapter-channel-lifecycle-relocation -->

- Provision the adapter's own per-session delivery channel via `ensure_channel`; channel-lifecycle mutation (create, rename, delete) is admin/Discord-only and not a UiAdapter responsibility.

<!-- /planned-change:adapter-channel-lifecycle-relocation -->

- Preserve origin-endpoint continuity for direct user replies.
- Decide local presentation strategy (edit-in-place, threaded, or multi-placement) for delivered messages.
- Store adapter-local delivery receipts for platform messages.

Boundaries

- No cross-computer orchestration responsibilities.
- No domain policy decisions; UI is translation and presentation only.
- No core-level routing assumptions for origin continuity; the extra admin reflection is routed upstream and only Discord renders it.
- No projection truth ownership. Adapter metadata is delivery receipt state only.

Invariants

- UI adapters do not mutate core state directly.
- Cleanup rules are enforced consistently for each session.

## Inputs/Outputs

**Inputs:**

- User commands (text, slash commands, button clicks)
- Voice messages (audio files requiring transcription)
- File uploads (documents, images, media)
- Domain events from EventBus (SESSION_UPDATED, SESSION_STATUS, TURN_COMPLETE, MESSAGE_SENT)
- Command results from CommandService

**Outputs:**

- Formatted UI messages (output, feedback, notices)
- Output message edits (in-place updates for streaming content)
- Channel/topic title updates with status emoji
- Message deletions per UX cleanup rules
- Platform-specific UI elements (buttons, inline keyboards, formatted text)

## Invariants

- **Read-Only Core State**: UI adapters never mutate session, database, or domain state directly; all writes via commands.
- **Platform-Agnostic Commands**: User actions normalized to command objects (CreateSessionCommand, SendMessageCommand); platform details in metadata only.
- **Consistent Cleanup Rules**: pending_message_deletions enforced uniformly across all UI adapters; trigger conditions identical.
- **Delivery Receipts Only**: Output message ids, char offsets, overflow state, and edit anchors are adapter-local receipts. They are not source truth and must not determine projection ordering.
  Core may ask UI adapters to clear these receipts at accepted-input time so the next assistant output opens a new platform message. The adapter records `turn_open_pending` only as a reconciliation marker for that cleared receipt; it is not turn truth.
- **Scope Contract**: Core defines recipients via delivery scope. Adapters must not broaden `ORIGIN_ONLY` recipient sets.
- **Reflection Contract**: Discord is the single admin adapter. Core sends the extra admin reflection only to Discord when the origin is not Discord. Telegram suppresses reflections entirely.
- **Origin Endpoint UX**: `ORIGIN_ONLY` messages appear only at the origin endpoint.
- **Summary Rule**: `last_output_summary` is origin-only and non-threaded only (in-edit UX path).
- **No Command Rebroadcast**: UI adapters do not rebroadcast command acknowledgements or lifecycle chatter to peer adapters.
- **No Turn Truth in Adapters**: UI adapters may clear or replace delivery receipts when rendering requires it, but source turn boundaries and projection cursors are owned upstream.

<!-- planned-change:adapter-channel-lifecycle-relocation -->

- **Destination-Addressed Delivery**: On the four delivery methods (`send_message`, `edit_message`, `delete_message`, `send_file`) the adapter receives a resolved `Destination` carrying its platform delivery coords plus any adapter-local delivery metadata needed to perform the send (e.g. WhatsApp's `last_customer_message_at`, which decides text-vs-template delivery inside the 24-hour customer window), never a `Session`. Platform coords are resolved upstream — by AdapterClient routing or a UiAdapter internal helper path, both through the shared core resolver — and the adapter parses the payload out without deriving its own destination. Channel-lifecycle methods remain session-shaped.

<!-- change:adapter-channel-lifecycle-relocation -->

- **Destination-Addressed Delivery**: On the four delivery methods (`send_message`, `edit_message`, `delete_message`, `send_file`) the adapter receives a resolved `Destination` carrying its platform delivery coords plus any adapter-local delivery metadata needed to perform the send (e.g. WhatsApp's `last_customer_message_at`, which decides text-vs-template delivery inside the 24-hour customer window), never a `Session`. Platform coords are resolved upstream — by AdapterClient routing or a UiAdapter internal helper path, both through the shared core resolver — and the adapter parses the payload out without deriving its own destination. Channel-lifecycle methods (`create_channel`, `update_channel_title`, `delete_channel`) are session-shaped and admin/Discord-only, hosted on the admin-reflection mixin rather than the universal UiAdapter contract.

<!-- /planned-change:adapter-channel-lifecycle-relocation -->

<!-- planned:adapter-inbound-core-seam -->

- **Inbound Resolve-Or-Create Seam**: An inbound message resolves to its bound session through the shared `core/inbound` seam, which the adapter feeds a thin per-adapter parse-in policy (identity-scoped lookup, create-with-bundled-first-message, metadata reconciliation, delivery). The seam returns `is_new`: a session created on this call has its first message bundled into the launch intent and receives no separate delivery, while an existing session's message is delivered unconditionally — no adapter gates inbound delivery on `lifecycle_status`. `on_session_status` is a presence-only path that drives the typing indicator and nothing else; the session-identification badge fires on the `accepted` boundary as a distinct concern.

<!-- /planned:adapter-inbound-core-seam -->

## Primary flows

### 1. Adapter Registration & Event Subscription

```mermaid
sequenceDiagram
    participant Daemon
    participant AdapterClient
    participant UiAdapter
    participant EventBus

    Daemon->>AdapterClient: Register adapter
    AdapterClient->>UiAdapter: __init__(client)
    UiAdapter->>EventBus: subscribe(SESSION_UPDATED, _handle_session_updated)
    UiAdapter->>EventBus: subscribe(SESSION_STATUS, _handle_session_status)
    UiAdapter->>EventBus: subscribe(TURN_COMPLETE, _handle_turn_complete)
    UiAdapter->>AdapterClient: Ready
```

### 2. Output Message Lifecycle

```mermaid
stateDiagram-v2
    [*] --> NoMessage: Session created
    NoMessage --> FirstSend: send_output_update()
    FirstSend --> Persisted: Store output_message_id
    Persisted --> Editing: send_output_update()
    Editing --> Editing: Edit succeeds
    Editing --> FirstSend: Edit fails (message deleted)
    Persisted --> Closed: Session ends
    Closed --> [*]
```

Accepted UI input opens a fresh output receipt at the core input acceptance
boundary (`deliver_inbound`), before the input is injected into the agent. The
adapter clears `output_message_id` and `char_offset`, records
`turn_open_pending`, and lets the next `send_output_update()` create a new
message instead of editing the prior turn. When the transcript later exposes the
same user boundary, `_maybe_clear_on_turn_boundary()` adopts the new
`turn_anchor_ts` and clears `turn_open_pending` without clearing the receipt a
second time. Turn truth stays upstream; only the adapter-local delivery receipt
is reset. Terminal-origin input has no UI acceptance boundary and keeps the
purely transcript-driven reset.

### 3. User Input Normalization

```mermaid
sequenceDiagram
    participant User
    participant Platform
    participant UiAdapter
    participant CommandMapper
    participant CommandService

    User->>Platform: Send message "hello"
    Platform->>UiAdapter: Handle update
    UiAdapter->>UiAdapter: Extract session from channel/topic
    UiAdapter->>UiAdapter: Validate user authorization
    UiAdapter->>CommandMapper: Map to SendMessageCommand
    CommandMapper->>CommandService: Execute command
    CommandService->>UiAdapter: Result
    UiAdapter->>User: Feedback "✅ Sent to AI"
```

### 4. UX Cleanup Rule Enforcement

```mermaid
flowchart TD
    MessageSent[Message sent to user]
    CheckTrigger{Cleanup trigger?}
    StoreInDB[Store message_id in pending_message_deletions]
    WaitForTrigger[Wait for trigger event]
    TriggerFires[Trigger event fires]
    FetchPending[Fetch pending_message_deletions]
    DeleteAll[Delete all tracked messages]
    ClearDB[Clear pending_message_deletions]
    Done[Cleanup complete]

    MessageSent --> CheckTrigger
    CheckTrigger -->|NEXT_NOTICE| StoreInDB
    CheckTrigger -->|TURN_COMPLETE| StoreInDB
    CheckTrigger -->|MANUAL| Done
    StoreInDB --> WaitForTrigger
    WaitForTrigger --> TriggerFires
    TriggerFires --> FetchPending
    FetchPending --> DeleteAll
    DeleteAll --> ClearDB
    ClearDB --> Done
```

### 5. Output Rendering Flow

```mermaid
sequenceDiagram
    participant Poller
    participant UiAdapter
    participant Platform
    participant DB

    Poller->>UiAdapter: send_output_update(session, output, is_final)
    UiAdapter->>UiAdapter: Truncate to max_message_size
    UiAdapter->>UiAdapter: Format with status line
    UiAdapter->>DB: Get output_message_id
    alt Message exists
        UiAdapter->>Platform: editMessage(message_id, formatted_output)
        Platform->>UiAdapter: Success
    else No message or edit fails
        UiAdapter->>Platform: sendMessage(formatted_output)
        Platform->>UiAdapter: new_message_id
        UiAdapter->>DB: Store output_message_id
    end
```

### 6. Session Title Synchronization

```mermaid
sequenceDiagram
    participant Core
    participant EventBus
    participant UiAdapter
    participant Platform

    Core->>EventBus: SESSION_UPDATED (title field)
    EventBus->>UiAdapter: _handle_session_updated(context)
    UiAdapter->>UiAdapter: Extract new title
    UiAdapter->>Platform: Update channel/topic title
    Platform->>UiAdapter: Success
```

### 7. Typing Indicator Flow

UI adapters fire platform typing indicators in response to lifecycle status events. This provides immediate user feedback that the agent is working.

| Status          | Trigger                                                   | Adapter Action                   |
| --------------- | --------------------------------------------------------- | -------------------------------- |
| `accepted`      | `user_prompt_submit` hook or UI input acceptance boundary | Request a throttled typing pulse |
| `active`        | `session_start` hook                                      | Request a throttled typing pulse |
| `active_output` | `tool_use` hook                                           | Request a throttled typing pulse |
| `completed`     | `agent_stop` hook                                         | Footer/badge decoration only     |

Typing is naturally replaced by output from the polling cadence (`send_output_update` at ~1s). UI adapters may only issue throttled typing pulses from lifecycle status transitions; tool-use churn must never call platform typing APIs directly. `active_output` is the status-derived activity pulse for ongoing agent work and must not render visible message content.

For UI-origin input, Core emits `accepted` at the input acceptance boundary
(`deliver_inbound`) so presence starts before any agent hook fires. The pulse
remains throttled and subject to the same origin/admin lane selection; only the
emission point moves earlier. Terminal-origin input keeps the late
`user_prompt_submit` source because it has no UI acceptance boundary.

### 8. Voice Message Processing

Voice transcription is durable across daemon restart and bounded against a hung
backend. The transcription runs as a tracked task (not awaited inline on the
adapter event loop) and its lifecycle is persisted in the daemon-owned
`voice_transcriptions` table. STT backends must keep blocking model setup and
transcription work off the event loop so the core wall-clock timeout remains
enforceable. The durability and recovery contract is
authoritative in `database#voice-transcription-durability-and-recovery` and
`daemon-lifecycle#post-adapter-completion-tasks`; this table is the happy-path
view.

UI adapters only download, send, edit, and delete platform messages; Core/Daemon
owns every `voice_transcriptions` row write and state transition (UI adapters
never mutate core state directly — see `#invariants` and
`layer-ownership#layer-boundaries`).

| Step | Actor     | Action                                                                                           |
| ---- | --------- | ------------------------------------------------------------------------------------------------ |
| 1    | User      | Sends voice message                                                                              |
| 2    | UiAdapter | Downloads audio file to `/tmp/teleclaude_voice/voice_*`                                          |
| 3    | UiAdapter | Dispatches `HandleVoiceCommand` through the daemon task registry and returns                     |
| 4    | Core      | Writes `voice_transcriptions` row `state=pending` (notice id NULL)                               |
| 5    | UiAdapter | Sends "🎤 Transcribing..." notice (origin-only); returns its platform msg id                     |
| 6    | Core      | Persists the returned id as `notice_message_id`; runs transcription as a tracked task            |
| 7    | STT       | Transcribes audio via the existing speech-to-text backend chain, bounded by a wall-clock timeout |
| 8    | UiAdapter | Edits the notice in place with the transcribed text or explicit failure                          |
| 9    | Core      | Transitions row to `succeeded` and sends the transcription through the normal message pipeline   |
| 10   | UiAdapter | Deletes voice message per cleanup rules (temp audio is swept by maintenance)                     |

Non-happy paths edit the **same** notice in place rather than emitting a
duplicate. Core drives the row's state and asks the adapter to edit: a
wall-clock timeout or terminal STT failure resolves the notice to an explicit
failure; on a daemon restart Core marks the row `interrupted` and the adapter
edits the notice in place (when a notice id was persisted), and the next boot's
recovery pass either completes the transcription or reports an audio-lost or
retry-cap failure. See the authoritative snippets above for the bounded-retry
and notice-ordering contract.

### 9. File Upload Flow

```mermaid
sequenceDiagram
    participant User
    participant Platform
    participant UiAdapter
    participant TmpFS
    participant AI

    User->>Platform: Upload document
    Platform->>UiAdapter: File update event
    UiAdapter->>Platform: Download file
    Platform->>TmpFS: Save to /tmp/{session_id}/{filename}
    UiAdapter->>AI: Send message with file_path
    UiAdapter->>User: "📎 Sent file: {filename}"
```

### 10. Reflection Routing

Core creates only the extra admin reflection, and only for Discord. The normal origin-path delivery is separate.

```mermaid
flowchart TD
    Origin["Origin input arrives"]
    IsDiscord{Origin is Discord?}
    NoExtra["No extra reflection copy"]
    DiscordOnly["Send extra reflection to Discord only"]
    Render["Discord renders with attribution<br/>(webhook, name, avatar)"]
    Telegram["Telegram suppresses reflections"]

    Origin --> IsDiscord
    IsDiscord -->|Yes| NoExtra
    IsDiscord -->|No| DiscordOnly
    DiscordOnly --> Render
    DiscordOnly --> Telegram
```

- Discord remains the only admin adapter.
- Telegram is an origin/input adapter only.
- Reflection suppression now happens before broad UI fanout, which avoids unnecessary lane work.
- Live output is now targeted at the origin UI adapter only. UI adapters never broaden that routing decision.
- Whether a user source entry is echoed, skipped, or reflected is decided by session projection before adapter rendering.

## Failure modes

- **Output Message Deleted by User**: Next edit fails. Adapter logs error, clears stale message_id, sends new message on next update.
- **Platform API Timeout**: Edit or send times out. Logged; polling retries next cycle. Output may be stale for 200ms.
- **Rate Limit Exceeded**: Platform rejects edit due to frequency. Adapter skips edit, accumulates diff, retries next cycle.
- **Session Channel Not Found**: Platform returns 404 on edit. Adapter clears metadata, recreates channel on next event.
- **Unauthorized User**: Message from non-whitelisted user. Silently ignored; no command execution or feedback.
- **Cleanup Message Already Deleted**: pending_message_deletions references deleted message. Delete fails gracefully; row cleared.
- **Feedback Routing Failure**: last_input_origin adapter offline. Feedback not delivered; logged. User sees nothing.
- **Adapter State Treated as Truth**: Invalid. A stale message id, char offset, or turn anchor may cause bad rendering, but it must not move the projection cursor or reorder source content.
- **Voice Transcription Failure**: The speech-to-text backend chain is unavailable, the audio format is unsupported, recovery cannot find the audio, or the retry cap is exceeded. User sees the original notice resolve to an explicit failure; source voice cleanup follows the normal cleanup rules.
- **File Download Failure**: Platform API error during download. User sees error feedback; no file sent to AI.
- **Multiple Adapters Active**: Origin-only feedback appears only on the origin endpoint. Non-origin endpoints rely on dual-lane stream traffic.
