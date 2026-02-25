# Implementation Plan - ucap-truthful-session-status

## Objective

Establish one core-owned lifecycle status contract and map it consistently to
Web, TUI, Telegram, Discord, and WhatsApp-capable presentation surfaces.

## Third-Party Inputs

- `docs/third-party/discord/bot-api.md`
- `docs/third-party/telegram/bot-api-status-and-message-editing.md`
- `docs/third-party/ai-sdk/ui-message-stream-status-parts.md`
- `docs/third-party/whatsapp/messages-api.md`

## Requirement Traceability

- `R1` -> Phase 1, Phase 2
- `R2` -> Phase 1, Phase 4
- `R3` -> Phase 3, Phase 4
- `R4` -> Phase 2, Phase 4
- `R5` -> Phase 4

## Phase 1 - Core Status Model and Contract

- [x] Define canonical status vocabulary and transition rules in shared core module(s).
- [x] Add typed payload schema/DTO for outbound lifecycle status events.
- [x] Add validation for allowed status values and required fields.
- [x] Enforce exact status set and required fields from requirements:
      `accepted`, `awaiting_output`, `active_output`, `stalled`, `completed`,
      `error`, `closed` and `session_id`, `status`, `reason`, `timestamp`,
      `last_activity_at` (when known).

### Files (expected)

- `teleclaude/core/events.py`
- `teleclaude/core/models.py`
- `teleclaude/api_models.py`
- shared serializer/contract modules under `teleclaude/core/*` or `teleclaude/api/*`

## Phase 2 - Truthful Transition Sources in Core

- [x] Wire status transitions to factual lifecycle signals:
  - session start / user prompt accepted
  - first output observed
  - inactivity/stall window reached
  - output resumes
  - stop/error/close
- [x] Ensure transitions are driven by transcript/output evidence and lifecycle state,
      not by adapter-local timers.
- [x] Keep hook events as bookkeeping/control-plane; no direct client status semantics
      are required from `tool_use`/`tool_done`.
- [x] Define core-owned stall threshold source and reason codes so transitions are
      deterministic and testable across adapters.

### Files (expected)

- `teleclaude/core/agent_coordinator.py`
- `teleclaude/core/polling_coordinator.py`
- `teleclaude/core/output_poller.py`
- `teleclaude/api_server.py`

## Phase 3 - Adapter Capability Mapping

- [x] Web: canonical lifecycle status events broadcast via WS (`session_status` type) — frontend consumes via `WsEvent` union.
- [x] Discord: implement one tracked editable status message per session thread.
- [x] Telegram: map canonical status into footer status line update path.
- [x] WhatsApp: no WhatsApp adapter present in codebase — skipped (no fabricated state).
- [x] TUI: consume the same canonical status state and present consistent semantics (stall/error notifications).
- [x] Persist Discord lifecycle status message identity in adapter metadata
      (for edit-in-place and duplicate prevention across updates/restarts).

### Files (expected)

- `frontend/components/assistant/*`
- `frontend/lib/ws/*`
- `frontend/app/api/chat/route.ts`
- `teleclaude/adapters/discord_adapter.py`
- `teleclaude/adapters/telegram_adapter.py`
- `teleclaude/adapters/whatsapp_adapter.py` (if present/enabled in this codebase)
- `teleclaude/adapters/ui_adapter.py`
- `teleclaude/cli/tui/*`

## Phase 4 - Validation and Observability

- [x] Add tests for canonical status vocabulary and transition correctness.
- [x] Add adapter tests for rendering/mapping behavior (Web, Discord, Telegram, TUI).
- [x] Add logs/metrics for transition reason and stale duration diagnostics.
- [x] Ensure transition telemetry includes `session_id`, `lane`, `from_status`,
      `to_status`, `reason`, and `last_activity_at` where available.
- [x] Verify no adapter emits contradictory semantic state.

### Files (expected)

- `tests/unit/test_agent_coordinator.py`
- `tests/unit/test_api_server.py`
- `tests/unit/test_discord_adapter.py`
- `tests/unit/test_ui_adapter.py`
- `tests/unit/test_telegram_adapter.py`
- `teleclaude/api/streaming.py`
- `teleclaude/api/transcript_converter.py`
- `teleclaude/core/models.py`
- `frontend` tests for status UI and stream handling

## Definition of Done

- [x] Core is the single source of truth for lifecycle status semantics.
- [x] All supported adapters map the same canonical statuses without semantic drift.
- [x] No-output stalls are surfaced truthfully and clear on resumed output.
- [x] Tests and docs cover vocabulary, transitions, and adapter mapping behavior.
