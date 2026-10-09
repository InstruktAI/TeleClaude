---
description: Telegram UI adapter that maps topics to sessions and enforces UX cleanup
  rules.
visibility: public
---

# Telegram Adapter — Design

## Required reads

- @docs/local/policy/ux-message-cleanup.md

## Purpose

- Provide the human-facing Telegram interface for sessions, commands, and streaming output.

- Commands, voice inputs, and file uploads map to explicit command objects and dispatch via CommandService.
- Session topics are created per session and named with the computer prefix.
- Output is streamed by editing a single persistent message per session.
- Heartbeats update a shared registry topic for peer discovery.

- Command registration is performed only by the master bot.
- BotCommand names include trailing spaces when published.
- Feedback and user input messages are deleted via pending_message_deletions rules.

- Missing topic threads trigger recovery and metadata repair before retry.
- Telegram API errors are logged and surfaced as adapter failures.
- Outbound methods gracefully skip if channel not ready; polling retries ensure eventual delivery.

## Inputs/Outputs

**Inputs:**

- Telegram bot commands from users (/start, /cancel, /kill, /clear, etc.)
- Private-chat `/start <parameter>` from a deep link, carrying an entry identifier: a member invitation token or a help desk's identifier

- Text messages (user input to AI)

- Voice messages (transcribed via the existing speech-to-text backend chain)
- File uploads (documents, images, audio)

- Telegram API webhooks (updates)

**Outputs:**

- Forum topics created per session (one topic = one session)
- Output messages edited in-place with streaming AI responses
- Temporary feedback messages (auto-deleted per UX cleanup rules)
- Topic title updates with session status emoji
- Registry heartbeats published to discovery topic
- Command registrations to Telegram bot scope

## Invariants

- **One Topic Per Session**: Each AI session maps to exactly one Telegram forum topic; topic_id stored in session metadata.
- **Master Bot Registration**: Only master bot publishes BotCommand list; slave bots skip registration.
- **Trailing Space in Commands**: Published BotCommand names include trailing space for Telegram client formatting.
- **Single Output Message**: One persistent output message per session, edited repeatedly; message_id stored in session metadata.
- **UX Cleanup Rules**: User input and feedback messages deleted per pending_message_deletions policy; output messages persist until session closes.

## Primary flows

### 1. Session Topic Creation

```mermaid
sequenceDiagram
    participant User
    participant TG as Telegram
    participant Adapter
    participant DB
    participant Daemon

    User->>TG: /start project-name "Do task"
    TG->>Adapter: Update (command, args)
    Adapter->>Adapter: Parse command + validate user
    Adapter->>Daemon: CreateSessionCommand
    Daemon->>DB: Create session record
    Daemon->>Adapter: SESSION_STARTED event
    Adapter->>Adapter: Acquire topic_creation_lock
    Adapter->>TG: createForumTopic(title="computer/agent: task")
    TG->>Adapter: topic_id
    Adapter->>DB: Update session with topic_id
    Adapter->>TG: Send initial output message
    TG->>Adapter: message_id
    Adapter->>DB: Update session with output_message_id
    Adapter->>Adapter: Release lock
```

### 2. Streaming Output Render

```mermaid
sequenceDiagram
    participant Poller
    participant Adapter
    participant TG as Telegram
    participant DB

    loop Output polling (200ms)
        Poller->>Adapter: NEW_TURN event (session_id, diff)
        Adapter->>DB: Get session metadata
        DB->>Adapter: topic_id, output_message_id
        Adapter->>Adapter: Append diff to buffer
        alt Rate limit ok (>1s since last edit)
            Adapter->>TG: editMessageText(output_message_id, full_buffer)
            TG->>Adapter: Success
        else Rate limit hit
            Adapter->>Adapter: Skip edit, accumulate
        end
    end
```

### 3. UX Message Cleanup

```mermaid
sequenceDiagram
    participant User
    participant TG as Telegram
    participant Adapter
    participant DB

    User->>TG: Text message
    TG->>Adapter: Update (message)
    Adapter->>Adapter: Resolve session
    Adapter->>DB: Store message_id in pending_message_deletions
    Adapter->>Daemon: SendMessageCommand
    Daemon->>Adapter: MESSAGE_SENT event
    Adapter->>TG: Send feedback "✅ Sent to AI"
    TG->>Adapter: feedback_message_id
    Adapter->>DB: Store feedback_message_id in pending_message_deletions

    Note over Daemon: AI completes turn

    Daemon->>Adapter: TURN_COMPLETE event
    Adapter->>DB: get_pending_message_deletions(session_id)
    DB->>Adapter: [user_message_id, feedback_message_id]
    loop For each message_id
        Adapter->>TG: deleteMessage(message_id)
    end
    Adapter->>DB: clear_pending_message_deletions(session_id)
```

### 4. Command Registration (Master Bot Only)

```mermaid
flowchart TD
    Start[Adapter start]
    IsMaster{is_master_bot?}
    GetCommands[Get command definitions]
    AddTrailingSpace[Add trailing space to names]
    Publish[setBotCommands with scope=chat]
    Skip[Skip registration]
    Done[Ready]

    Start --> IsMaster
    IsMaster -->|Yes| GetCommands
    IsMaster -->|No| Skip
    GetCommands --> AddTrailingSpace
    AddTrailingSpace --> Publish
    Publish --> Done
    Skip --> Done
```

### 5. Voice Message Handling

The Telegram adapter owns only Telegram-specific message operations (extract
session from topic, download the audio, send/edit/delete platform messages).
Transcription durability — the `voice_transcriptions` row lifecycle, the tracked
transcription task, the wall-clock timeout, bounded restart recovery, and
edit-in-place notice semantics — is owned by Core/Daemon and is authoritative in
`database#voice-transcription-durability-and-recovery` and
`daemon-lifecycle#post-adapter-completion-tasks`. The adapter does not transcribe
inline and does not own the row.

```mermaid
sequenceDiagram
    participant User
    participant TG as Telegram
    participant Adapter
    participant Daemon
    participant Core
    participant STT as Voice Service

    User->>TG: Send voice message
    TG->>Adapter: Update (voice)
    Adapter->>Adapter: Extract session from topic
    Adapter->>TG: getFile(file_id)
    TG->>Adapter: file_path
    Adapter->>TG: Download voice file
    Adapter->>Daemon: Spawn HandleVoiceCommand via task_registry and return
    Daemon->>Core: Create/reuse durable voice_transcriptions row
    Core->>Adapter: Send or edit "🎤 Transcribing..." notice
    Adapter->>TG: Send/edit notice; return platform message id
    Core->>Core: Persist notice id and drive row state
    Core->>STT: Transcribe audio with timeout
    STT->>Core: Transcribed text or failure
    Core->>Adapter: Edit original notice to result/failure
    Adapter->>TG: Edit message
    Core->>Daemon: ProcessMessageCommand(transcribed_text)
```

Telegram owns Telegram-specific extraction, authorization, download, and message
operations. It does not transcribe inline and does not own recovery state. Voice
work runs as a daemon-tracked task so shutdown can mark an in-progress row
interrupted while Telegram is still available for an in-place notice edit.
Startup recovery later resubmits surviving audio or edits the original notice to
an explicit audio-lost/retry-cap failure.

### 6. Topic Title Status Updates

| Status  | Emoji | Trigger                              |
| ------- | ----- | ------------------------------------ |
| active  | 🟢    | AI responding, output streaming      |
| waiting | 🟡    | Waiting for user input               |
| slow    | 🟠    | Turn exceeds 30s                     |
| stalled | 🔴    | Turn exceeds 120s                    |
| idle    | ⏸️    | Session paused or no recent activity |
| dead    | ❌    | Session ended or crashed             |

### 7. Registry Heartbeat Publishing

```mermaid
sequenceDiagram
    participant Adapter
    participant TG as Telegram
    participant DiscoveryTopic

    loop Every 60s
        Adapter->>Adapter: Collect active computers
        Adapter->>Adapter: Build registry message
        Adapter->>TG: editMessageText(registry_message_id, formatted_list)
        TG->>DiscoveryTopic: Update "Online Computers" message
    end
```

### 8. File Upload Flow

| File Type | Processing                                     | Output                               |
| --------- | ---------------------------------------------- | ------------------------------------ |
| Document  | Download → save to /tmp → send file_path to AI | AI receives file path for processing |
| Image     | Download → send to AI with caption             | AI analyzes image content            |
| Audio     | Download → transcribe → send text to AI        | AI receives transcribed text         |

### 9. Private-Chat Entry

<!-- planned-change:help-desk-master-routing -->

A private chat is one person's conversation with this computer's bot. The adapter carries the entry identifier as the `/start` parameter (`third-party/telegram/deep-linking`); it recognises the identifier, hands it to the core, and otherwise finds the person's latest session by its origin metadata, as for every adapter (`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`). It holds no routing rules of its own.

```mermaid
flowchart TD
    IN[Private message or /start with parameter] --> ID{Carries an entry identifier?}
    ID -->|Yes| CORE[Core resolves it to an endpoint]
    CORE -->|Endpoint hosted here| NEW[New session at the endpoint]
    CORE -->|Nothing servable here| NEUTRAL[Neutral reply, no session]
    ID -->|No| LOOKUP[Latest session by origin metadata]
    LOOKUP --> DECIDE[Core decides: that session, the role fallback, or the neutral reply]
```

<!-- change:help-desk-master-routing -->

A private chat is one person's conversation with this computer's bot. The adapter carries the entry identifier as the `/start` parameter (`third-party/telegram/deep-linking`); it recognises the identifier, hands it to the core, and otherwise finds the chat's session by its origin metadata, as for every adapter (`local/projects/teleclaude/spec/feature/agent_runtime/conversation-entry`). It holds no routing rules of its own. A desk identifier reaches a desk only on the master's bot.

```mermaid
flowchart TD
    IN[Private message or /start with parameter] --> ID{Carries an entry identifier?}
    ID -->|Yes| CORE[Core resolves it to an endpoint]
    CORE -->|Member's assistant, or a desk on the master| PERSON[The person's session there: continue, revive, or create]
    CORE -->|Nothing servable here| NEUTRAL[Neutral reply, no session]
    ID -->|No| LOOKUP[The chat's session by origin metadata]
    LOOKUP --> DECIDE[Core decides: that session revived when closed, the person's own assistant, or the neutral reply]
```

<!-- /planned-change:help-desk-master-routing -->

Voice messages and files in a private chat take the same path as text: a sender whose chat reaches no endpoint gets the neutral reply instead of a silent drop.

## Failure modes

- **Topic Creation Race**: Two events try to create topic simultaneously. Lock prevents duplicate creation; second attempt skips.
- **Missing Topic Metadata**: Session has no topic_id. Recovery flow creates new topic and updates metadata.
- **Telegram API Timeout**: Edit or send fails due to network. Logged; next polling cycle retries. Message may be stale.
- **Rate Limit Exceeded**: Too many edits in 1s window. Adapter skips edit, accumulates diff, retries next cycle.

- **Voice Transcription Failure**: The speech-to-text backend chain is unavailable or returns an error, the audio format is unsupported, recovery cannot find the audio, or the retry cap is exceeded. User sees the original notice resolve to an explicit failure; voice message cleanup follows the normal cleanup rules.

- **Master Bot Conflict**: Multiple bots claim master role. Last one wins; command list overwritten. Coordinated config required.
- **Output Message Deleted**: User manually deletes output message. Next edit fails; adapter creates new output message.
- **Cleanup Failure**: pending_message_deletions row exists but message already deleted. Logged; row cleared on next cleanup.

<!-- planned-change:help-desk-master-routing -->

- **Entry Identifier for an Endpoint Hosted Elsewhere**: The identifier resolves to an endpoint this computer does not host. The sender gets the neutral reply; no session is created here or on the hosting computer, because this bot is the only one the sender reached.

<!-- change:help-desk-master-routing -->

- **Desk Identifier on a Bot That Is Not the Master's**: Help desks run only on the master, so a desk identifier sent to another computer's bot reaches nothing. The sender gets the neutral reply and no session is created on any computer, because this bot is the only one the sender reached.

<!-- /planned-change:help-desk-master-routing -->
