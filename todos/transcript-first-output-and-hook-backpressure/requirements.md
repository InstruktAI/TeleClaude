# Requirements - transcript-first-output-and-hook-backpressure

## Problem

Output updates are currently produced by multiple paths:

- Hook-driven incremental triggers (`tool_use` / `tool_done`).
- Poller-driven transcript/tmux change detection.

This creates duplicate fanout, event floods, noisy logs, and backlog in hook processing. In bursty sessions (especially Gemini), hook traffic can lag far behind real transcript progress, causing stale control events while output has already moved on.

## Goal

Harmonize output and event processing so the system is deterministic under load:

1. Single output data plane based on transcript deltas.
2. Hooks remain control-plane signals, not output fanout producers.
3. Bounded hook processing with coalescing/backpressure so queue lag cannot grow unbounded.

## In Scope

- Output path unification to one cadence-driven producer.
- Removal of hook-triggered output fanout for tool events.
- Hook queue backpressure/coalescing policy.
- Control-plane vs data-plane contract documentation.
- Metrics and observability for lag, coalescing, and output cadence.

## Out of Scope

- New adapter providers.
- Major UI redesign.
- Replacing transcript parsing engine itself.
- Changing authentication/role semantics.

## Functional Requirements

### R1. Single output producer

- Only one component may emit adapter output updates for session transcript progression.
- `tool_use`/`tool_done` hooks must not directly trigger output fanout.
- Output must continue to progress from transcript/source-of-truth deltas on the configured cadence.

### R2. Hook role is control plane only

- Hook events remain authoritative for lifecycle/control state:
  - session start/end
  - input notifications
  - activity/audit metadata
- Hook processing must not be required for output timeline progression.

### R3. Backpressure and coalescing

- Hook processing pipeline must be bounded.
- For bursty event classes, implement coalescing policy (latest-wins or per-turn aggregate where applicable).
- Critical control events must never be dropped.
- Baseline classification for this todo:
  - `critical`: `session_start`, `user_prompt_submit`, `agent_stop`, `session_end`, `notification`, `error`
  - `bursty`: `tool_use`, `tool_done`
- New non-critical hook variants default to `bursty` until explicitly promoted.

### R4. Deterministic output cadence

- Output updates follow configured cadence (default target 1.0s).
- Cadence may be tuned later (for example 0.5s) without architectural changes.
- Final turn flush must still occur on session stop/exit.

### R5. Observability

- Emit metrics for:
  - hook queue depth
  - hook processing lag
  - coalesced event count
  - output tick cadence and fanout volume
- Add clear log lines for suppression/coalescing summaries, not per-event spam.

## Non-Functional Requirements

- No regression in correctness of delivered output.
- Stable behavior under high-volume tool event sessions.
- Keep failure modes explicit and debuggable.

## Acceptance Criteria

1. Transcript-driven output remains continuous while hook bursts occur.
2. `tool_use`/`tool_done` no longer trigger direct output fanout.
3. Hook backlog cannot grow unbounded under sustained burst load.
4. `p95` hook processing lag is below 1s in normal load; `p99` below 3s, measured by a synthetic burst test added in this todo.
5. No duplicate output emission caused by dual producer paths.
6. Logs and/or counters show periodic coalescing/suppression summaries instead of per-event flood lines.

## Risks

- Partial migration can leave mixed old/new paths and reintroduce duplicates.
- Over-aggressive coalescing could hide useful diagnostics if not instrumented well.
