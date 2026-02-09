# Requirements: Web Interface — Phase 1: Daemon SSE Plumbing

## Goal

Add daemon-side infrastructure for the web interface: TCP port, SSE streaming endpoint, transcript converter, people list, and message ingestion.

## Functional Requirements

### FR1: TCP port binding

- Expose FastAPI app on `localhost:8420` alongside existing Unix socket.
- Both serve the same app. No duplication.

### FR2: SSE streaming endpoint

- `POST /api/chat/stream` returns `StreamingResponse` with `media_type="text/event-stream"`.
- Response header: `x-vercel-ai-ui-message-stream: v1`.
- Request body: `sessionId` (required), `since_timestamp` (optional for reconnect), `messages` (optional for new user input).
- Two modes: history replay then live streaming.
- Message lifecycle: `start` → content events → `finish` → `[DONE]`.

### FR3: Transcript-to-SSE converter

- Claude JSONL `thinking` → `reasoning-start` / `reasoning-delta` / `reasoning-end`.
- Claude JSONL `tool_use` → `tool-input-start` / `tool-input-available`.
- Claude JSONL `tool_result` → `tool-output-available`.
- Claude JSONL `text` → `text-start` / `text-delta` / `text-end`.
- `send_result` → `data-send-result` custom part.
- Session status → `data-session-status` custom part.

### FR4: People list endpoint

- `GET /api/people` returns list of `{name, email, role}` from global config.
- No credentials or sensitive fields exposed.

### FR5: Message ingestion

- When request includes new user message in `messages` array, extract last message text.
- Send to session via `send_keys` (tmux bridge).
- Begin streaming response.

## Acceptance Criteria

1. Daemon serves on `localhost:8420` and Unix socket simultaneously.
2. SSE endpoint produces valid AI SDK v5 UIMessage Stream.
3. Transcript replay converts JSONL to correct SSE event types.
4. Live streaming from output poller produces real-time SSE events.
5. People list returns correct data without sensitive fields.
6. User message sent via SSE endpoint reaches tmux session.

## Dependencies

- **person-identity-auth** — auth middleware must be active on new endpoints.
- **config-schema-validation** — people list from validated global config.
