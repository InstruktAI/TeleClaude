# Requirements: Web Interface

## Goal

Build a Next.js 15 web application bridged to TeleClaude via Vercel AI SDK v5, providing a chat interface with authentication, streaming output, and session management.

## Problem Statement

TeleClaude's current interfaces (Telegram, TUI, MCP) serve power users. The web interface solves two problems: (1) approachable chat UI for non-power-users, and (2) authentication surface for multi-person deployments where login flows, email verification, and role-based views need to live.

## Scope

### In scope

**Daemon-side:**

1. **TCP port binding** — expose API on `localhost:8420` alongside Unix socket.
2. **SSE streaming endpoint** — `POST /api/chat/stream` producing AI SDK v5 UIMessage Stream.
3. **Transcript-to-SSE converter** — JSONL → structured SSE events.
4. **People list endpoint** — `GET /api/people` from config.
5. **Message ingestion** — user text → `send_keys` to tmux session.

**Frontend:** 6. **NextAuth v5 email OTP** — Brevo SMTP, 6-digit code, database sessions (DrizzleAdapter + SQLite). 7. **Vercel AI SDK v5** — `useChat` with `DefaultChatTransport` consuming daemon SSE. 8. **UIMessage part rendering** — React components for reasoning, tool-call, text, data-send-result, file parts. 9. **Session management views** — sidebar session list, session view with chat stream, session creation. 10. **Role-based visibility** — private sessions by default, admin sees all, shared session support.

### Out of scope

- Terminal emulator (no xterm.js).
- Mobile-first design.
- Full prompt injection ML model (pattern-based detection only in v1).
- Replacing the TUI.
- Public internet exposure (localhost only in v1).

## Functional Requirements

### FR1: Daemon SSE streaming endpoint

- `POST /api/chat/stream` returns Server-Sent Events with `x-vercel-ai-ui-message-stream: v1` header.
- Two modes: (1) history replay from JSONL transcript, (2) live streaming from output poller.
- Event types: `reasoning-start/delta/end`, `text-start/delta/end`, `tool-input-start/available`, `tool-output-available`, custom `data-*` parts.
- Message lifecycle: `start` → content events → `finish` → `[DONE]`.

### FR2: Transcript-to-SSE conversion

- Claude JSONL `thinking` → `reasoning-start/delta/end`.
- Claude JSONL `tool_use` → `tool-input-start/available`.
- Claude JSONL `tool_result` → `tool-output-available`.
- Claude JSONL `text` → `text-start/delta/end`.
- `send_result` artifacts → `data-send-result` custom part.

### FR3: Authentication

- NextAuth v5 with Email provider (6-digit OTP, 3-minute expiry).
- Brevo SMTP transport (adopted from ai-chatbot).
- User verification against people config (unknown emails rejected).
- Session callback enriches with role from config.
- SQLite for NextAuth session/token storage (localhost deployment).
- 30-day cookie lifetime.

### FR4: Chat interface

- `useChat` with `DefaultChatTransport` pointing at daemon SSE proxy.
- Input box sends messages → daemon ingests via `send_keys`.
- UIMessage parts rendered by type-specific React components.
- `since_timestamp` on reconnect to avoid replaying full history.

### FR5: Session management

- Sidebar: active sessions with title, agent icon, last activity.
- Session switching (SSE stream follows selected session).
- "New Session" with project/agent picker.
- Session actions: end session.

### FR6: Role-based visibility

- Default: private (only creator sees output).
- Admin: sees all sessions.
- Shared sessions: admin can mark sessions visible to members.
- SSE endpoint checks person + role + visibility before streaming.

### FR7: People list and login flow

- `GET /api/people` returns people from global config.
- Login page shows people dropdown → email resolved → OTP flow.

## Non-functional Requirements

1. Localhost deployment: Next.js standalone on `localhost:3003`, daemon on `localhost:8420`.
2. Two processes: daemon (Python) + web (Node.js). Same machine.
3. Coexists with TUI, Telegram, MCP — another adapter, not a replacement.
4. SSE streaming must not block on slow clients.

## Acceptance Criteria

1. Daemon serves SSE stream that `useChat` consumes correctly.
2. Transcript replay converts JSONL to correct SSE event types.
3. Live streaming updates appear in real-time in the browser.
4. Email OTP login works with people config verification.
5. Role-based session visibility enforced.
6. UIMessage parts render correctly (reasoning, tool-call, text, artifacts).
7. Session list shows active sessions with real-time status.
8. New session creation works from browser.

## Dependencies

- **config-schema-validation** — PersonEntry with email + role.
- **person-identity-auth** — session-to-person binding, auth middleware, role resolution.
- **output-streaming-unification** — canonical activity stream (recommended but not blocking for basic SSE).

## Technology Stack

- Next.js 15 (App Router, standalone output)
- Vercel AI SDK v5 (`@ai-sdk/react`, `ai`)
- NextAuth v5 (email OTP, DrizzleAdapter)
- Brevo SMTP (`nodemailer-brevo-transport`)
- Drizzle ORM (SQLite for localhost)
- shadcn/ui + Tailwind
- react-markdown + remark-gfm
