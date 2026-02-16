# Requirements: Web Interface Phase 3 — Chat Interface & Part Rendering

## Goal

Replace the placeholder chat adapter with real SSE streaming and build React components that render each UIMessage part type produced by the daemon.

## Problem Statement

Phase 2 delivered a working scaffold with auth and API route proxies, but the chat interface uses a non-streaming `ChatModelAdapter` that does a single `fetch` + `res.json()`. The daemon's SSE streaming endpoint (`POST /api/chat/stream`) produces rich AI SDK v5 UIMessage Stream events (reasoning, tool calls, text, custom data parts), but the frontend cannot consume them. Phase 3 bridges this gap.

## Scope

### In scope

1. **Streaming runtime** — Replace `useLocalRuntime` + `ChatModelAdapter` with `useChatRuntime` from `@assistant-ui/react-ai-sdk`, consuming the daemon SSE stream via the existing `/api/chat` proxy route.
2. **Session ID wiring** — Allow selecting which TeleClaude session to stream (URL query param + minimal session picker). Phase 4 handles the full sidebar.
3. **UIMessage part components**:
   - `<ThinkingBlock>` — Collapsible reasoning (collapsed by default).
   - `<ToolCallBlock>` — Tool name badge, collapsible args and result.
   - `<MarkdownContent>` — react-markdown + remark-gfm for text parts.
   - `<ArtifactCard>` — Rendered `send_result` content (markdown or HTML).
   - `<StatusIndicator>` — Session status from `data-session-status` events.
   - `<FileLink>` — Clickable link resolving to daemon file endpoint.
4. **Chat input** — `sendMessage` delivers text to the daemon via the existing proxy, which ingests it via tmux `send_keys`.
5. **Reconnection** — Use `since_timestamp` on reconnect to avoid replaying full history.

### Out of scope

- Session list sidebar with session switching (phase 4).
- Session creation flow with project/agent picker (phase 4).
- Role-based visibility filtering (phase 4).
- Admin dashboard (phase 4).
- Mobile responsive design.

## Functional Requirements

### FR1: Streaming transport

- Replace `useLocalRuntime` + `ChatModelAdapter` with `useChatRuntime` backed by the AI SDK v5 transport.
- The transport targets `/api/chat` (existing proxy route) which forwards to daemon `/api/chat/stream`.
- The `sessionId` is included in every request body so the daemon knows which session to stream.
- Messages stream in real-time as SSE events are received.
- When the stream finishes (receives `[DONE]`), the status transitions from streaming to idle.

### FR2: Session selection

- Accept `sessionId` from URL query parameter (`?sessionId=xxx`).
- Show a minimal session dropdown at the top of the chat page, populated from `GET /api/sessions`.
- Selecting a session navigates to `/?sessionId=<id>` and reconnects the stream.
- If no sessionId is provided, show the session picker prompt instead of the chat.

### FR3: Part rendering — reasoning

- `reasoning` parts render as a collapsible `<ThinkingBlock>`.
- Collapsed by default, showing a "Thinking..." label with expand/collapse toggle.
- Expanded view shows the full reasoning text with monospace or subdued styling.

### FR4: Part rendering — tool calls

- `tool-call` parts render as a `<ToolCallBlock>` showing the tool name as a badge.
- Args are collapsible (collapsed by default for common tools, expanded for unknown tools).
- When a matching `tool-result` part arrives, the result is shown below the args.
- Error results are styled distinctly (red/warning).

### FR5: Part rendering — text

- `text` parts render through `<MarkdownContent>` using react-markdown + remark-gfm.
- Supports: headings, lists, code blocks with syntax highlighting, tables, links, bold/italic.
- Code blocks use a syntax highlighter (e.g., `rehype-highlight` or `shiki`).

### FR6: Part rendering — custom data parts

- `data-send-result` renders as an `<ArtifactCard>` — a bordered card with markdown or HTML content.
- `data-session-status` updates a `<StatusIndicator>` showing session state (streaming, idle, closed, error).
- Unknown `data-*` parts are silently ignored (no crash).

### FR7: Part rendering — files

- `file` parts render as a `<FileLink>` with the filename and a download/open icon.
- Clicking opens the file via daemon file endpoint (proxied through Next.js if needed).

### FR8: Chat input

- Text input at the bottom of the chat sends messages via `sendMessage`.
- The message is delivered to the daemon which injects it into the tmux session.
- Input is disabled while the assistant is actively streaming (or shows a stop button).
- Enter key sends the message; Shift+Enter inserts a newline.

## Non-functional Requirements

1. Streaming latency: first SSE event visible in UI within 500ms of daemon producing it.
2. No full-page re-renders on each SSE event — incremental updates only.
3. All part components handle missing/malformed data gracefully (no crash).
4. Accessible: keyboard navigation for collapsible blocks, ARIA attributes on interactive elements.

## Acceptance Criteria

1. Opening `/?sessionId=<valid-id>` connects to the SSE stream and renders messages in real-time.
2. Reasoning parts appear as collapsible blocks, collapsed by default.
3. Tool call parts show tool name, and collapsible args/result.
4. Text parts render full markdown including code blocks with syntax highlighting.
5. Typing a message and pressing Enter delivers it to the daemon session.
6. Session picker shows available sessions and navigating between them works.
7. `data-session-status` updates the status indicator without page reload.

## Dependencies

- **web-interface-1** (delivered) — daemon SSE endpoint + transcript converter.
- **web-interface-2** (delivered) — Next.js scaffold, auth, API route proxies.

## Technology Additions

- `@assistant-ui/react-ai-sdk` — bridge between assistant-ui primitives and AI SDK v5 transport.
- `@ai-sdk/react` + `ai` — Vercel AI SDK v5 core (peer dependency of the bridge).
- `rehype-highlight` or `shiki` — code block syntax highlighting.
- `remark-gfm` — GitHub Flavored Markdown support (tables, strikethrough, etc.).
