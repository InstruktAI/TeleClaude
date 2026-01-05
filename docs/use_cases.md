# TeleClaude Use Cases

**Last Updated:** 2025-01-08

This document describes all user interaction scenarios with TeleClaude, including sequence diagrams for each use case.

---

## Table of Contents

1. [Human-Interactive Use Cases](#human-interactive-use-cases)
2. [AI-to-AI Use Cases](#ai-to-ai-use-cases)
3. [Session Management Use Cases](#session-management-use-cases)
4. [Voice Interaction Use Cases](#voice-interaction-use-cases)
5. [Multi-Adapter Broadcasting](#multi-adapter-broadcasting)

---

## Human-Interactive Use Cases

These use cases involve a human user interacting with TeleClaude via Telegram.

### UC-H1: Create New Terminal Session

**Actor:** Human user via Telegram

**Trigger:** User sends `/new` command in Telegram

**Flow:**

```mermaid
sequenceDiagram
    participant User
    participant TG as TelegramAdapter
    participant Client as AdapterClient
    participant Daemon
    participant DB as db
    participant tmux

    User->>TG: /new "My Session"
    TG->>Client: handle_event(NEW_SESSION, title="My Session")
    Client->>Daemon: handle_new_session()

    Note over Daemon: Generate session_id
    Daemon->>DB: create_session(origin_adapter="telegram")
    DB-->>Daemon: Session created

    Note over Daemon: Create channel in origin adapter
    Daemon->>Client: create_channel(session_id, title)
    Client->>TG: create_channel()
    TG-->>Client: channel_id="123"

    Note over Daemon: Update session with channel_id
    Daemon->>DB: update_session(adapter_metadata={"channel_id": "123"})

    Note over Daemon: Create tmux session
    Daemon->>tmux: create_session(session_id)
    tmux-->>Daemon: Session ready

    Client->>TG: send_message("Session created!")
    TG-->>User: "✅ Session 'My Session' created"
```

**Postconditions:**

- New session in database with `origin_adapter="telegram"`
- Telegram topic created
- tmux session running
- User can send commands

---

### UC-H2: Execute Terminal Command (Human Mode)

**Actor:** Human user via Telegram

**Trigger:** User types command in session topic

**Flow:**

```mermaid
sequenceDiagram
    participant User
    participant TG as TelegramAdapter
    participant Client as AdapterClient
    participant Daemon
    participant DB as db
    participant tmux
    participant Poller as OutputPoller

    User->>TG: "ls -la" in topic
    TG->>Client: handle_event(MESSAGE, text="ls -la")
    Client->>Daemon: handle_message()

    Note over Daemon: Get session
    Daemon->>DB: get_session(session_id)
    DB-->>Daemon: Session (origin_adapter="telegram")

    Note over Daemon: Send to terminal
    Daemon->>tmux: send_keys("ls -la")

    Note over Daemon: Start output polling
    Daemon->>Poller: poll_and_send_output(session_id)

    Note over Poller: Poll every 1 second
    loop Every 1s
        Poller->>tmux: capture_pane()
        tmux-->>Poller: output

        Note over Poller: Human mode - edit same message
        Poller->>Client: send_output_update(session_id, output)
        Client->>TG: edit_message(message_id, formatted_output)
        TG-->>User: Shows live output
    end

    Note over Poller: Detect shell return
    Poller->>tmux: capture_pane()
    tmux-->>Poller: "...files..."

    Note over Poller: Send final status
    Poller->>Client: send_output_update(is_final=True)
    Client->>TG: edit_message(message_id, final_output)
    TG-->>User: "✅ Completed"
```

**Key Behaviors (Human Mode):**

- First 10 seconds: Edit same message in-place (clean UX)
- After 10 seconds: Send new messages (preserve history)
- Output formatted with status line: `⏱️ Running 2m 34s | 📊 145KB`
- Completion status shown in final message
- Idle notification after 60s (auto-deleted when output resumes)

---

### UC-H3: Long-Running Command with Idle Notification

**Actor:** Human user via Telegram

**Trigger:** User runs command that produces no output for 60+ seconds

**Flow:**

```mermaid
sequenceDiagram
    participant User
    participant TG as TelegramAdapter
    participant Client as AdapterClient
    participant Poller as OutputPoller
    participant DB as db

    User->>TG: "sleep 120"
    Note over TG,Poller: (Command execution as UC-H2)

    Note over Poller: No output change for 60s
    Poller->>Client: send_message("⏳ No output for 60s...")
    Client->>TG: send_message()
    TG-->>User: Idle notification

    Note over Poller: Store notification message_id
    Poller->>DB: set_idle_notification_message_id(msg_id)

    Note over Poller: Output resumes
    Poller->>Client: send_output_update(output)

    Note over Poller: Delete idle notification
    Poller->>DB: get_idle_notification_message_id()
    DB-->>Poller: msg_id
    Poller->>Client: delete_message(msg_id)
    Client->>TG: delete_message()

    Note over Poller: Continue polling until exit
```

**Key Points:**

- Idle notification is informational only (does NOT stop polling)
- Auto-deleted when output resumes
- Polling continues until exit code detected

---

### UC-H4: Download Large Output

**Actor:** Human user via Telegram

**Trigger:** Command output exceeds 3800 characters

**Flow:**

```mermaid
sequenceDiagram
    participant User
    participant TG as TelegramAdapter
    participant Client as AdapterClient
    participant UiAdapter
    participant DB as db
    participant FS as FileSystem

    User->>TG: "cat large_file.log"
    Note over TG,UiAdapter: (Command execution as UC-H2)

    Note over UiAdapter: Output > 3800 chars
    UiAdapter->>UiAdapter: Truncate to last 3400 chars
    UiAdapter->>Client: send_message(truncated + status_line)
    Client->>TG: send_message() with download button
    TG-->>User: Truncated output + [📎 Download]

    User->>TG: Clicks download button
    TG->>Client: handle_event(CALLBACK_QUERY)
    Client->>Daemon: handle_callback_query()

    Note over Daemon: Read full output file
    Daemon->>FS: read(session_output/abc123.txt)
    FS-->>Daemon: full_output

    Note over Daemon: Create temp file
    Daemon->>FS: write(/tmp/output_abc123.txt)

    Note over Daemon: Send as document
    Daemon->>Client: send_document(session_id, temp_file)
    Client->>TG: send_document()
    TG-->>User: File download

    Note over Daemon: Cleanup temp file
    Daemon->>FS: unlink(/tmp/output_abc123.txt)
```

**Key Points:**

- Truncation preserves last N chars (most recent output)
- Full output always persisted to `session_output/{session_id}.txt`
- Temp file cleaned up in `finally` block
- Download available until session ends

---

### UC-H5: Send Voice Command

**Actor:** Human user via Telegram

**Trigger:** User sends voice message in session topic

**Flow:**

```mermaid
sequenceDiagram
    participant User
    participant TG as TelegramAdapter
    participant Client as AdapterClient
    participant Daemon
    participant Whisper
    participant DB as db

    User->>TG: [Voice message]
    TG->>Client: handle_event(VOICE_MESSAGE, file_id)
    Client->>Daemon: handle_voice_message()

    Note over Daemon: Download voice file
    Daemon->>TG: download_file(file_id)
    TG-->>Daemon: voice.ogg

    Note over Daemon: Send status to user
    Daemon->>Client: send_status_message("🎤 Transcribing...", append=True)
    Client->>TG: edit_message(output_message_id, status)
    TG-->>User: Shows transcription status

    Note over Daemon: Transcribe with Whisper
    Daemon->>Whisper: transcribe(voice.ogg)
    Whisper-->>Daemon: "list files in home directory"

    Note over Daemon: Cleanup temp voice file
    Daemon->>FS: unlink(voice.ogg)

    Note over Daemon: Show transcription, ask confirmation
    Daemon->>Client: send_message("Transcribed: 'list files...'\n[Execute] [Cancel]")
    Client->>TG: send_message() with inline keyboard
    TG-->>User: Confirmation buttons

    User->>TG: Clicks [Execute]
    TG->>Client: handle_event(CALLBACK_QUERY, action="execute")
    Client->>Daemon: handle_callback_query()

    Note over Daemon: Execute as normal command
    Daemon->>tmux: send_keys("list files in home directory")

    Note over Daemon: (Continue as UC-H2)
```

**Key Points:**

- Transcription status appended to existing output message (clean UX)
- User must confirm before execution (safety)
- Temp voice file cleaned up after transcription
- Executed command appears in terminal history

---

## AI-to-AI Use Cases

These use cases involve cross-computer orchestration where one AI controls another computer's terminal.

### UC-A1: AI Initiates Cross-Computer Session

**Actor:** AI (Claude Code) via MCP on Computer A

**Trigger:** AI calls `create_session` MCP tool

**Flow:**

```mermaid
sequenceDiagram
    participant AI as Claude Code (A)
    participant MCP_A as MCP Server (A)
    participant Redis_A as RedisAdapter (A)
    participant RedisDB as Redis Server
    participant Redis_B as RedisAdapter (B)
    participant Daemon_B as Daemon (B)
    participant DB_B as db (B)
    participant tmux_B as tmux (B)

    AI->>MCP_A: create_session(computer="B", title="Deploy")
    MCP_A->>Redis_A: create_channel(title, metadata={is_ai_to_ai: true})

    Note over Redis_A: Publish to Redis stream
    Redis_A->>RedisDB: XADD sessions {computer: B, title: Deploy}

    Note over Redis_B: Polling detects new session request
    Redis_B->>RedisDB: XREAD sessions
    RedisDB-->>Redis_B: {computer: B, title: Deploy}

    Note over Redis_B: Emit event
    Redis_B->>Daemon_B: handle_event(NEW_SESSION)
    Daemon_B->>DB_B: create_session(origin_adapter="redis", is_ai_to_ai=true)
    DB_B-->>Daemon_B: Session created

    Daemon_B->>tmux_B: create_session(session_id)
    tmux_B-->>Daemon_B: Ready

    Note over Redis_B: Confirm to Redis
    Redis_B->>RedisDB: XADD responses {session_id: abc, status: ready}

    Note over Redis_A: Poll for response
    Redis_A->>RedisDB: XREAD responses
    RedisDB-->>Redis_A: {session_id: abc, status: ready}

    Redis_A-->>MCP_A: {session_id: "abc"}
    MCP_A-->>AI: Session created
```

**Key Points:**

- Session marked with `is_ai_to_ai=true` in metadata
- No Telegram topic created (Redis-only transport)
- Session persists across daemon restarts (SQLite)

---

### UC-A2: AI Executes Remote Command (AI Mode)

**Actor:** AI (Claude Code) via MCP on Computer A

**Trigger:** AI calls `execute_command` MCP tool

**Flow:**

```mermaid
sequenceDiagram
    participant AI as Claude Code (A)
    participant MCP_A as MCP Server (A)
    participant Redis_A as RedisAdapter (A)
    participant RedisDB as Redis Server
    participant Redis_B as RedisAdapter (B)
    participant Daemon_B as Daemon (B)
    participant tmux_B as tmux (B)
    participant Poller_B as OutputPoller (B)

    AI->>MCP_A: execute_command(session_id, "git status")
    MCP_A->>Redis_A: send_command_to_computer(command)
    Redis_A->>RedisDB: XADD commands {session_id, command: "git status"}

    Note over Redis_B: Poll for commands
    Redis_B->>RedisDB: XREAD commands
    RedisDB-->>Redis_B: {command: "git status"}

    Redis_B->>Daemon_B: handle_event(MESSAGE, text="git status")
    Daemon_B->>tmux_B: send_keys("git status")

    Note over Poller_B: AI mode - send RAW chunks
    Poller_B->>tmux_B: capture_pane()
    tmux_B-->>Poller_B: output chunk 1

    Poller_B->>Redis_B: send_message(session_id, raw_chunk_1)
    Redis_B->>RedisDB: XADD output {chunk: "On branch main..."}

    Note over Redis_A: Poll output stream
    Redis_A->>RedisDB: XREAD output
    RedisDB-->>Redis_A: {chunk: "On branch main..."}

    Redis_A-->>MCP_A: yield chunk_1
    MCP_A-->>AI: chunk_1 (raw text, NO backticks)

    Note over Poller_B: Continue until shell returns
    Poller_B->>tmux_B: capture_pane()
    tmux_B-->>Poller_B: "...files..."

    Poller_B->>Redis_B: send_message("[Output Complete]")
    Redis_B->>RedisDB: XADD output {marker: "[Output Complete]"}

    Redis_A->>RedisDB: XREAD output
    RedisDB-->>Redis_A: {marker: "[Output Complete]"}
    Redis_A-->>MCP_A: Stream complete
    MCP_A-->>AI: Command finished
```

**Key Behaviors (AI Mode):**

- Output sent as RAW chunks (no backticks, no formatting)
- No message editing (sequential chunks)
- Chunk size: 3900 chars
- 0.1s delay between chunks (preserve order)
- `[Output Complete]` marker signals end of stream

---

### UC-A3: AI Polls Output Stream

**Actor:** AI (Claude Code) via MCP on Computer A

**Trigger:** AI calls `poll_output_stream` MCP tool (for long-running commands)

**Flow:**

```mermaid
sequenceDiagram
    participant AI as Claude Code (A)
    participant MCP_A as MCP Server (A)
    participant Redis_A as RedisAdapter (A)
    participant RedisDB as Redis Server

    Note over AI: After execute_command, poll for updates
    AI->>MCP_A: poll_output_stream(session_id, timeout=300)

    loop Until timeout or "[Output Complete]"
        MCP_A->>Redis_A: poll_output_stream(session_id)
        Redis_A->>RedisDB: XREAD output BLOCK 1000

        alt New output available
            RedisDB-->>Redis_A: {chunk: "Progress: 50%"}
            Redis_A-->>MCP_A: yield chunk
            MCP_A-->>AI: chunk
        else Timeout (1s)
            RedisDB-->>Redis_A: (empty)
            Note over Redis_A: Continue polling
        end

        alt Completion marker received
            RedisDB-->>Redis_A: {marker: "[Output Complete]"}
            Redis_A-->>MCP_A: Stream complete
            MCP_A-->>AI: Done
        end
    end
```

**Key Points:**

- Streaming API (async generator)
- Blocks for 1s per XREAD (efficient)
- Timeout configurable (default 300s)
- AI can process chunks as they arrive

---

## Session Management Use Cases

### UC-S1: List Active Sessions

**Actor:** Human user via Telegram

**Trigger:** User sends `/list` command

**Flow:**

```mermaid
sequenceDiagram
    participant User
    participant TG as TelegramAdapter
    participant Client as AdapterClient
    participant Daemon
    participant DB as db
    participant tmux

    User->>TG: /list
    TG->>Client: handle_event(COMMAND, command="list")
    Client->>Daemon: handle_command("list")

    Daemon->>DB: list_sessions()
    DB-->>Daemon: [Session1, Session2, Session3]

    loop For each session
        Daemon->>tmux: list_sessions() filter by name
        tmux-->>Daemon: session exists/missing
    end

    Note over Daemon: Format list with status
    Daemon->>Client: send_message(formatted_list)
    Client->>TG: send_message()
    TG-->>User: "📋 Active Sessions:\n1. Session1 ✅\n2. Session2 ⚠️ (tmux died)"
```

---

### UC-S2: End Session

**Actor:** Human user via Telegram

**Trigger:** User sends `/exit` command in topic

**Flow:**

```mermaid
sequenceDiagram
    participant User
    participant TG as TelegramAdapter
    participant Client as AdapterClient
    participant Daemon
    participant DB as db
    participant tmux
    participant FS as FileSystem

    User->>TG: /exit
    TG->>Client: handle_event(COMMAND, command="exit")
    Client->>Daemon: handle_command("exit")

    Note over Daemon: Stop polling if active
    Daemon->>DB: unmark_polling(session_id)

    Note over Daemon: Kill tmux session
    Daemon->>tmux: kill_session(tmux_session_name)
    tmux-->>Daemon: Killed

    Note over Daemon: Delete output file
    Daemon->>FS: unlink(session_output/abc123.txt)

    Note over Daemon: Delete session record
    Daemon->>DB: delete_session(session_id)

    Note over Daemon: Delete Telegram topic
    Daemon->>Client: delete_channel(session_id)
    Client->>TG: delete_topic()

    Client->>TG: send_message("Session ended")
    TG-->>User: "✅ Session ended"
```

**Key Points:**

- Stops output polling
- Kills tmux session
- Deletes output file (cleanup)
- Deletes session from DB
- Deletes Telegram topic

---

### UC-S3: Session Recovery After Daemon Restart

**Actor:** System (daemon startup)

**Trigger:** Daemon restarts

**Flow:**

```mermaid
sequenceDiagram
    participant Daemon
    participant DB as db
    participant tmux
    participant TG as TelegramAdapter

    Note over Daemon: Daemon starting
    Daemon->>DB: list_sessions()
    DB-->>Daemon: [Session1, Session2]

    loop For each active session
        Daemon->>tmux: list_sessions() filter by name

        alt tmux session exists
            tmux-->>Daemon: Session alive
            Note over Daemon: Session restored
        else tmux session missing
            tmux-->>Daemon: Not found
            Note over Daemon: Terminate and delete
            Daemon->>DB: delete_session(session_id)
        end
    end
```

**Key Points:**

- Sessions persist in SQLite
- tmux sessions may survive daemon restart
- Dead tmux sessions auto-detected and terminated
- No output polling resumed (user must send new command)

---

## Voice Interaction Use Cases

### UC-V1: Voice Command Confirmation Flow

See [UC-H5: Send Voice Command](#uc-h5-send-voice-command)

---

### UC-V2: Voice Transcription Error Handling

**Actor:** Human user via Telegram

**Trigger:** Whisper transcription fails

**Flow:**

```mermaid
sequenceDiagram
    participant User
    participant TG as TelegramAdapter
    participant Client as AdapterClient
    participant Daemon
    participant Whisper

    User->>TG: [Voice message]
    TG->>Client: handle_event(VOICE_MESSAGE)
    Client->>Daemon: handle_voice_message()

    Daemon->>Client: send_status_message("🎤 Transcribing...")
    Client->>TG: edit_message(status)
    TG-->>User: Shows status

    Daemon->>Whisper: transcribe(voice.ogg)
    Whisper-->>Daemon: Error (file corrupted)

    Note over Daemon: Log error, notify user
    Daemon->>Client: send_message("❌ Transcription failed. Try again.")
    Client->>TG: send_message()
    TG-->>User: Error message
```

---

## Multi-Adapter Broadcasting

### UC-M1: Telegram User with Redis Observer

**Actor:** Human user via Telegram (origin), AI observing via Redis

**Trigger:** User executes command

**Flow:**

```mermaid
sequenceDiagram
    participant User
    participant TG as TelegramAdapter<br/>(origin)
    participant Client as AdapterClient
    participant Daemon
    participant Redis as RedisAdapter<br/>(observer)
    participant AI as Claude Code

    User->>TG: "npm test"
    Note over TG,Daemon: (Execute as UC-H2)

    Note over Daemon: Send output
    Daemon->>Client: send_message(session_id, output)

    Note over Client: Send to origin (CRITICAL)
    Client->>TG: send_message()
    TG-->>User: Shows output

    Note over Client: Broadcast to observers with has_ui=True
    Client->>Redis: ❌ SKIP (has_ui=False)

    Note over Redis: RedisAdapter has has_ui=False
    Note over Redis: Pure transport, no UI broadcasts
```

**Key Point:** RedisAdapter does NOT receive broadcasts because `has_ui=False` (pure transport).

---

### UC-M2: Multiple UI Observers (Future)

**Actor:** Human user via Telegram (origin), Slack observer (future)

**Trigger:** User executes command

**Flow:**

```mermaid
sequenceDiagram
    participant User
    participant TG as TelegramAdapter<br/>(origin)
    participant Client as AdapterClient
    participant Slack as SlackAdapter<br/>(observer, has_ui=True)

    User->>TG: "ls -la"
    Note over TG,Client: (Execute command)

    Note over Client: Send to origin
    Client->>TG: send_message()
    TG-->>User: Shows output

    Note over Client: Broadcast to observers with has_ui=True
    Client->>Slack: send_message() [best-effort]

    alt Slack success
        Slack-->>Client: OK
        Note over Client: Log success
    else Slack failure
        Slack-->>Client: Error
        Note over Client: Log warning, continue
    end
```

**Key Points:**

- Origin adapter: CRITICAL (failure raises exception)
- Observer adapters: Best-effort (failures logged)
- Only observers with `has_ui=True` receive broadcasts

---

## Summary

### Use Case Categories

| Category                    | Count | Description              |
| --------------------------- | ----- | ------------------------ |
| Human-Interactive (UC-H\*)  | 5     | User via Telegram UI     |
| AI-to-AI (UC-A\*)           | 3     | Cross-computer via Redis |
| Session Management (UC-S\*) | 3     | Lifecycle operations     |
| Voice (UC-V\*)              | 2     | Voice transcription      |
| Multi-Adapter (UC-M\*)      | 2     | Broadcasting patterns    |

### Key Behavioral Differences

| Aspect             | Human Mode                 | AI Mode                   |
| ------------------ | -------------------------- | ------------------------- |
| Output formatting  | Formatted with status line | RAW chunks                |
| Message editing    | Edit in-place (first 10s)  | No editing, sequential    |
| Chunking           | Single message (truncated) | Multiple 3900-char chunks |
| Completion marker  | Exit code in message       | `[Output Complete]`       |
| Idle notifications | Yes (after 60s)            | No                        |
| Download buttons   | Yes (if > 3800 chars)      | No (full streaming)       |

---

**End of Use Cases Document**
