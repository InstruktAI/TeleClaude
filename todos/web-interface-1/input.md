# Web Interface — Phase 1: Daemon SSE Plumbing

## Context

This is phase 1 of the web-interface breakdown. See the parent todo's
`input.md` and `implementation-plan.md` for full architectural context.

## Intended Outcome

Add daemon-side infrastructure for the web interface: TCP port binding,
SSE streaming endpoint producing AI SDK v5 UIMessage Stream, transcript-to-SSE
converter, people list endpoint, and message ingestion path.

## What to Build

1. **TCP port binding** — expose API on `localhost:8420` alongside existing Unix socket.
2. **SSE streaming endpoint** — `POST /api/chat/stream` producing AI SDK v5 UIMessage Stream with `x-vercel-ai-ui-message-stream: v1` header.
3. **Transcript-to-SSE converter** — JSONL transcript entries → structured SSE events (reasoning, tool-call, text, custom parts).
4. **People list endpoint** — `GET /api/people` returns people from global config.
5. **Message ingestion** — user text extracted from request → `send_keys` to tmux session.

## Key Architectural Notes

- SSE endpoint has two modes: history replay (from JSONL transcript) then live streaming (from output poller events).
- `StreamingResponse` with `media_type="text/event-stream"`.
- AI SDK wire protocol: `data: {json}\n\n` format.
- Auth middleware from person-identity-auth must be active on these endpoints.

## Verification

- `curl http://localhost:8420/health` returns OK (TCP binding).
- `curl -X POST http://localhost:8420/api/chat/stream` receives SSE events.
- Transcript converter unit tests with sample JSONL → expected SSE output.
- People list returns correct data.
