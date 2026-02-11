# Roadmap

> **Last Updated**: 2026-02-11
>
> **Status**: `[ ]` Pending | `[.]` Ready (has requirements) | `[>]` In Progress
>
> Delivered items are listed in [delivered.md](./delivered.md). The roadmap focuses on upcoming work and high-level initiatives, while delivered.md serves as a comprehensive > > changelog of completed tasks. This separation allows the roadmap to remain forward-looking and strategic, while still providing a detailed record of past accomplishments in > delivered.md.
>
> **Other lists**:
> [delivered.md](./delivered.md) — completed work |
> [icebox.md](./icebox.md) — parked, no active priority

---

## Daemon-Independent Jobs

- [.] daemon-independent-jobs — Subprocess-based agent job execution with role-aware invocation

Replace daemon-dependent `POST /sessions` agent job spawning with direct subprocess invocation. Agent jobs get full tool and MCP access, fall back silently to admin role when daemon is unavailable. Cron plist auto-installed by `make init`, 5-minute trigger granularity, overlap prevention, `--list` shows all job types. No hard dependencies — current prepare jobs work immediately.

## Person Identity & Authentication

- [.] person-identity-auth — **BROKEN DOWN**

Daemon-side identity infrastructure for multi-person deployments. PersonEntry config model, identity resolver, session-to-person binding, auth middleware, token signing, human-role tool gating, and adapter integration. Four roles: admin, member, contributor, newcomer. Login flows (email OTP) are handled by web-interface, not here.

- [.] person-identity-auth-1 — Identity Model & Config
- [.] person-identity-auth-2 (after: person-identity-auth-1) — Session Binding & Auth Middleware
- [.] person-identity-auth-3 (after: person-identity-auth-2) — Role Gating & Adapter Integration

## Help Desk Platform

- [.] help-desk (after: person-identity-auth-3)

Establish `help-desk` as the universal entry point for external interactions. Implements the "Help Desk Trap" (forced routing to `help-desk` project for non-admin identities) and dual-profile agent configuration (`default` vs `restricted`). Restricts file access via settings.json denial rules and CLI flags, while allowing explicit doc mounts.

- [.] help-desk-clients (after: help-desk, agent-activity-events)

Connect external messaging platforms (WhatsApp, Discord) to the Help Desk lobby. Implements "Admin Supergroup" observability where all customer sessions are mirrored to a Telegram Control Room for real-time monitoring and intervention. Updates AdapterClient for multi-destination routing.

## Agent Activity Events

- [>] agent-activity-events-phase-3-7

Complete remaining phases of agent-activity-events: DB column rename (last_tool_use_at, last_tool_done_at), event vocabulary rename (tool_use, tool_done), comprehensive test coverage for event emission and broadcast, documentation updates, and final validation. Closes the gap from Phase 1-2 foundation to production-ready event pipeline.

## Release Automation

- [.] release-automation

A fully automated release pipeline where a dedicated AI inspector analyzes diffs on every main push, decides whether to release (patch/minor) based on contract manifests, and creates releases automatically with generated notes. Features a dual-lane pipeline (Claude Code + Codex CLI) and a consensus arbiter.

## Session Messages API

- [.] session-messages-api — Structured messages endpoint from native session files

Structured `GET /sessions/{id}/messages` endpoint backed by native transcript files. Accumulates transcript file paths per session (chain storage) instead of replacing on rotation. Extracts structured message objects (role, type, text, timestamp) from Claude/Codex/Gemini JSONL/JSON files. Exposes compaction events as first-class system messages. Supports incremental fetch via `since` timestamp. Prerequisite for web-interface SSE plumbing.

## Web Interface

- [ ] web-interface (after: person-identity-auth, agent-activity-events) — **BROKEN DOWN**

Next.js 15 web application bridged to TeleClaude via Vercel AI SDK v5. Daemon produces AI SDK UIMessage Stream (SSE) from session transcripts and live output. Frontend uses `useChat` with `DefaultChatTransport`. Auth via NextAuth email OTP (6-digit code, Brevo SMTP adopted from ai-chatbot). Session-to-person metadata binding with visibility routing. React components for each UIMessage part type (reasoning, tool-call, text, custom data parts for send_result artifacts and file links).

- [.] web-interface-1 (after: session-messages-api, person-identity-auth) — Daemon SSE Plumbing
- [ ] web-interface-2 (after: web-interface-1) — Next.js Scaffold & Auth
- [ ] web-interface-3 (after: web-interface-2) — Chat Interface & Part Rendering
- [ ] web-interface-4 (after: web-interface-3) — Session Management & Role-Based Access

## Role-Based Notifications

- [.] role-based-notifications

Notification routing subsystem that sends job outputs, reports, and alerts to people based on their role and channel subscriptions in per-person teleclaude.yml. Generalizes the existing personal Telegram script into a multi-person delivery layer.
