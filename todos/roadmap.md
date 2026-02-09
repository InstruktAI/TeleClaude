# Roadmap

> **Last Updated**: 2026-02-09
>
> **Status**: `[ ]` Pending | `[.]` Ready (has requirements) | `[>]` In Progress | `[x]` Done
>
> **Other lists**:
> [delivered.md](./delivered.md) — completed work |
> [icebox.md](./icebox.md) — parked, no active priority

---

## Config Schema Validation

- [.] config-schema-validation

Pydantic-based schema for teleclaude.yml across all three config levels (project, global, per-person). Enforce level constraints (only global can configure `people`), validate before interpreting/merging, fix interests schema mismatch (flat list vs nested dict in discovery.py).

## Job Contract Refinements

- [x] job-contract-refinements (after: config-schema-validation)

Agent jobs use `job` field (spec doc reference) instead of inline `message`. Add job validation to `telec sync` pipeline. Fix discovery.py interests handling. Lightweight input declarations for jobs that need per-person data.

## Eliminate Raw SQL from DB Layer

- [.] db-raw-sql-cleanup

Convert inline SQL in db.py to SQLModel/SQLAlchemy ORM and enforce via pre-commit hook.

## Dependency Health Guardrails

- [.] dependency-health-guardrails

Introduce dependency health guardrails (API + Redis) with circuit-breaker behavior and destructive-op safety gates so timeouts and outages never trigger unsafe cleanup/termination paths.

## Next Prepare Maintenance Runner

- [x] next-prepare-maintenance

Maintenance routine that audits active todos for Definition-of-Ready quality, improves `requirements.md` and `implementation-plan.md` in-place when safe, writes `DOR report.md`, and stores a `state.json` DOR quality score (`1..10`) with escalation status.

## Merge Runner

- [.] merge-runner

Serialized merge-only integration runner. It promotes approved worktree branches into `main` one at a time from an isolated merge workspace, updates roadmap/delivered on success, and stops on first conflict with a clear report.

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

## Role-Based Notifications

- [.] role-based-notifications (after: config-schema-validation)

Notification routing subsystem that sends job outputs, reports, and alerts to people based on their role and channel subscriptions in per-person teleclaude.yml. Generalizes the existing personal Telegram script into a multi-person delivery layer.
