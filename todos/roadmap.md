# Roadmap

> **Last Updated**: 2026-02-09
>
> **Status**: `[ ]` Pending | `[.]` Ready (has requirements) | `[>]` In Progress | `[x]` Done
>
> **Other lists**:
> [delivered.md](./delivered.md) — completed work |
> [icebox.md](./icebox.md) — parked, no active priority

---

## Person Identity & Authentication

- [.] person-identity-auth (after: config-schema-validation) — **BROKEN DOWN**

Daemon-side identity infrastructure for multi-person deployments. PersonEntry config model, identity resolver, session-to-person binding, auth middleware, token signing, human-role tool gating, and adapter integration. Four roles: admin, member, contributor, newcomer. Login flows (email OTP) are handled by web-interface, not here.

- [.] person-identity-auth-1 (after: config-schema-validation) — Identity Model & Config
- [.] person-identity-auth-2 (after: person-identity-auth-1) — Session Binding & Auth Middleware
- [.] person-identity-auth-3 (after: person-identity-auth-2) — Role Gating & Adapter Integration

## Agent Logbook — Per-Agent Observability

- [.] agent-logbook-observability

Per-session structured logging via SQLite `agent_logs` table. Write API (`POST /api/logbook`), read API with filtering, and MCP tool (`teleclaude__write_log`). Agents write security events, decision trails, job results, performance data. Foundation for web interface security dashboards and job runner observability.

## Output Streaming Unification

- [.] output-streaming-unification

Target-state outbound architecture: canonical agent activity stream events (`user_prompt_submit`, `agent_output_update`, `agent_output_stop`) routed through AdapterClient/distributor to Telegram/TUI/Web consumers, while cache/API websocket stays focused on state snapshots.

## Web Interface

- [ ] web-interface (after: person-identity-auth, output-streaming-unification) — **BROKEN DOWN**

Next.js 15 web application bridged to TeleClaude via Vercel AI SDK v5. Daemon produces AI SDK UIMessage Stream (SSE) from session transcripts and live output. Frontend uses `useChat` with `DefaultChatTransport`. Auth via NextAuth email OTP (6-digit code, Brevo SMTP adopted from ai-chatbot). Session-to-person metadata binding with visibility routing. React components for each UIMessage part type (reasoning, tool-call, text, custom data parts for send_result artifacts and file links).

- [.] web-interface-1 (after: person-identity-auth, config-schema-validation) — Daemon SSE Plumbing
- [ ] web-interface-2 (after: web-interface-1) — Next.js Scaffold & Auth
- [ ] web-interface-3 (after: web-interface-2) — Chat Interface & Part Rendering
- [ ] web-interface-4 (after: web-interface-3) — Session Management & Role-Based Access

## Context-Aware Checkpoint (Phase 2)

- [.] agent-output-monitor

Context-aware checkpoint messages at agent stop boundaries. Inspects git diff to categorize changed files and produces specific validation instructions (restart daemon, SIGUSR2 TUI, run tests) instead of generic checkpoint text. Shared builder used by both hook (Claude/Gemini) and tmux (Codex) delivery paths.

## Role-Based Notifications

- [.] role-based-notifications (after: config-schema-validation)

Notification routing subsystem that sends job outputs, reports, and alerts to people based on their role and channel subscriptions in per-person teleclaude.yml. Generalizes the existing personal Telegram script into a multi-person delivery layer.
