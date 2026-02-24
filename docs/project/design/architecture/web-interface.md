---
id: 'project/design/architecture/web-interface'
type: 'design'
scope: 'project'
description: 'High-level architecture of the TeleClaude Next.js web interface.'
---

# Web Interface Architecture — Design

## Required reads

- @project/design/architecture/web-api-facade
- @project/spec/identity-and-auth

## Purpose

Provide a real-time chat experience, session management, and dashboard for internal staff, acting as a canonical Web API facade for the TeleClaude network.

## Inputs/Outputs

- **Inputs:** Human user input (chat, session controls, settings), TeleClaude Daemon SSE stream, Redis Stream-backed WebSocket messages.
- **Outputs:** Real-time chat UI, session status indicators, diagnostic dashboard, proxy requests to `/tmp/teleclaude-api.sock`.

## Invariants

- All core data requests are proxied through the Web API facade to the Daemon.
- Authentication must be verified via NextAuth for all protected routes.
- The UI must maintain visual parity with the TeleClaude TUI (Master Source design tokens).

## Primary flows

### 1. Real-time Message Streaming

User sends a message via the `AssistantChatTransport`. The request is transformed and proxied to the Daemon's `/api/chat/stream`. The resulting SSE stream is cleaned (suppressing internal checkpoints and technical command bodies) before being rendered.

### 2. WebSocket Bridging

Browser WebSockets connect to `/api/ws`. The custom `server.ts` validates the session cookie and upgrades the connection to bridge directly to the Daemon's transport layer.

## Failure modes

- **Daemon Unreachable:** UI displays a "Disconnected" or "Reconnecting" badge and gracefully handles proxy errors (503 Service Unavailable).
- **Session Expired:** Next.js middleware redirects unauthorized requests to `/login`.
- **Stream Invalidation:** Custom SSE events that do not adhere to the AI SDK protocol are filtered to prevent frontend validation crashes.
