# Requirements - ucap-truthful-session-status

## Problem

Session lifecycle feedback is inconsistent across clients. Some lanes rely on
optimistic typing or local heuristics, while others show little or no explicit
state. This creates a trust gap: users cannot reliably tell whether a request
was received, is actively producing output, is stalled, or has completed.

## Goal

Define one truthful lifecycle status contract in core and require every adapter
to render that same truth according to platform capabilities.

## Dependency

- Must run after `ucap-canonical-contract`.

## In Scope

- Core-owned lifecycle status derivation.
- Canonical status vocabulary and payload fields for outbound fanout.
- Adapter capability mapping for Web, TUI, Telegram, Discord, and WhatsApp (when enabled).
- Truthful stall/inactivity handling that does not pretend activity.
- Regression tests and observability for status transitions.

## Out of Scope

- Replacing transcript parsing implementation.
- Reintroducing hook-driven output fanout.
- Major visual redesign of client UIs beyond status surfaces.

## Functional Requirements

### R1. Core-owned status truth

- Core computes lifecycle status from factual signals (session lifecycle,
  accepted user input, transcript/output progression, stop/error/close).
- Client adapters must not invent or infer semantic status independently.
- `tool_use`/`tool_done` are not required as client-facing status drivers.

### R2. Canonical status contract

- One shared outbound status payload is defined for all adapter lanes.
- Required fields include: `session_id`, `status`, `reason`, `timestamp`,
  and `last_activity_at` (when known).
- Allowed status values are explicitly documented and validated:
  - `accepted`
  - `awaiting_output`
  - `active_output`
  - `stalled`
  - `completed`
  - `error`
  - `closed`

### R3. Capability-aware adapter rendering

- Web renders status outside threaded messages (status bar/line near composer).
- Discord renders status via one dedicated editable status message per thread.
- Telegram renders status via footer metadata update path.
- WhatsApp maps canonical status to platform-compatible activity/read-state semantics
  without inventing false typing promises.
- TUI renders status from the same canonical stream/state contract.
- Adapter mappings must preserve canonical semantics even when UI primitives differ.

### R4. Truthful inactivity behavior

- Optimistic states (for example `accepted`) must expire into truthful waiting/stall
  states when no output evidence appears.
- Stalled state must clear automatically when output resumes.
- Completed/error/closed terminal states must replace transient activity states.

### R5. Observability and validation

- Status transition logs/metrics include session id, lane, from->to, and reason.
- Tests cover normal flow, no-output stall, recovery from stall, and terminal states.

## Acceptance Criteria

1. Core emits canonical lifecycle status transitions without requiring adapter-local heuristics.
2. Web shows truthful status outside the message thread.
3. Discord maintains exactly one editable status message per active session thread.
4. Telegram/TUI consume the same core status truth and remain semantically aligned.
5. A no-output scenario transitions to `stalled` and later returns to active/completed when output appears.
6. Contract and adapter regression tests assert status vocabulary and transition behavior.

## Risks

- Overly aggressive stall timing can create false positives under heavy model load.
- Partial rollout can produce inconsistent status semantics between adapters.
- If adapter persistence for status message IDs is incomplete, Discord status messages may duplicate.

## Third-Party Research Inputs

- `docs/third-party/discord/bot-api.md`
- `docs/third-party/telegram/bot-api-status-and-message-editing.md`
- `docs/third-party/ai-sdk/ui-message-stream-status-parts.md`
- `docs/third-party/whatsapp/messages-api.md`
