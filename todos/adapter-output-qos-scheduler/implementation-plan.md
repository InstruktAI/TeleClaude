# Implementation Plan: adapter-output-qos-scheduler

## Overview

Implement adapter-wide output QoS in two layers:

1. **Transport safety (library-native):**
   - Enable PTB rate limiter for Telegram API calls.
2. **Product behavior (thin TeleClaude layer):**
   - Coalesce superseded output updates per session.
   - Apply fairness and dynamic pacing derived from active emitting sessions and configured budget.

This keeps custom logic focused on output freshness/fairness while delegating API flood control to official SDK mechanisms.

## Phase 1: Config + Policy Skeleton

### Task 1.1: Add QoS config schema

**File(s):**

- `teleclaude/config/__init__.py`
- `config.sample.yml`

- [ ] Add adapter QoS config structures and defaults (Telegram strict defaults, Discord/WhatsApp off/coalesce-only defaults).
- [ ] Validate config parsing and backward compatibility with existing configs.

### Task 1.2: Define adapter policy contract

**File(s):**

- `teleclaude/adapters/qos/policy.py` (new)
- `teleclaude/adapters/qos/__init__.py` (new)

- [ ] Define policy interface for:
  - coalescing strategy
  - budget computation
  - priority class mapping
  - optional per-adapter hard limits
- [ ] Provide `TelegramOutputPolicy`, `DiscordOutputPolicy`, `WhatsAppOutputPolicy` placeholders.

---

## Phase 2: Scheduler Core

### Task 2.1: Build generic output scheduler

**File(s):**

- `teleclaude/adapters/qos/output_scheduler.py` (new)

- [ ] Implement in-memory session queues keyed by `(adapter, session_id)`.
- [ ] Implement latest-only payload replacement for normal priority events.
- [ ] Implement priority lane for final/completion updates.
- [ ] Implement fair dispatch (round-robin across active emitting sessions).
- [ ] Implement tick computation helpers with 100ms rounding.

### Task 2.2: Add instrumentation

**File(s):**

- `teleclaude/adapters/qos/output_scheduler.py` (new)
- `teleclaude/services/monitoring_service.py` (if needed)

- [ ] Emit metrics/log summaries:
  - queue depth
  - dropped/superseded payload count
  - effective dispatch cadence
  - per-session wait age
  - retry-after incidence by adapter

---

## Phase 3: Telegram Integration

### Task 3.1: Enable PTB limiter in adapter startup

**File(s):**

- `teleclaude/adapters/telegram_adapter.py`
- `pyproject.toml`

- [ ] Wire `Application.builder().rate_limiter(...)` using PTB supported limiter.
- [ ] Add/install dependency support for PTB rate-limiter extra.
- [ ] Ensure startup behavior is explicit if rate-limiter dependency is missing.

### Task 3.2: Route Telegram output through scheduler

**File(s):**

- `teleclaude/adapters/telegram_adapter.py`
- `teleclaude/adapters/ui_adapter.py` (minimal hook points only)
- `teleclaude/core/adapter_client.py` (only if required for clean hook insertion)

- [ ] Apply scheduler to Telegram output methods for both:
  - `send_output_update`
  - `send_threaded_output`
- [ ] Ensure non-blocking integration (shared fanout path remains free of sleep).
- [ ] Ensure `is_final` flush behavior and deterministic cleanup on close.

### Task 3.3: Preserve existing fallback behavior

**File(s):**

- `teleclaude/adapters/telegram/message_ops.py`

- [ ] Keep retry wrappers as fallback safety.
- [ ] Remove only duplicated custom pacing logic (if superseded by scheduler + PTB limiter).

---

## Phase 4: Discord/WhatsApp Policy Rollout

### Task 4.1: Discord coalesce-only mode

**File(s):**

- `teleclaude/adapters/discord_adapter.py`
- `teleclaude/adapters/qos/policy.py`

- [ ] Add opt-in coalesce-only mode for Discord output.
- [ ] Keep strict caps off by default.

### Task 4.2: WhatsApp policy stub

**File(s):**

- `teleclaude/adapters/qos/policy.py`

- [ ] Add policy stub and config slots for future adapter.
- [ ] Document required external limit validation before enablement.

---

## Phase 5: Testing + Validation

### Task 5.1: Unit tests

**File(s):**

- `tests/unit/test_output_qos_scheduler.py` (new)
- `tests/unit/test_telegram_adapter_rate_limiter.py` (new)
- `tests/unit/test_threaded_output_updates.py` (update)
- `tests/unit/test_polling_coordinator.py` (update if integration points change)

- [ ] Verify cadence math and rounding.
- [ ] Verify coalescing (latest-only) and superseded drop accounting.
- [ ] Verify fairness across many active sessions.
- [ ] Verify final-priority flush behavior.
- [ ] Verify threaded/non-threaded parity and no regression in output continuity.

### Task 5.2: Integration/load checks

**File(s):**

- `tests/integration/test_telegram_output_qos_load.py` (new, if feasible)
- `scripts/` load harness (optional)

- [ ] Simulate `N=20` active emitting sessions.
- [ ] Confirm sustained operation without runaway flood-control retries.
- [ ] Confirm queue stabilization and bounded staleness.

### Task 5.3: Runtime validation

- [ ] `make restart`
- [ ] `make status`
- [ ] `instrukt-ai-logs teleclaude --since 15m --grep "Output cadence summary|Rate limited|qos|scheduler"`
- [ ] Validate final-message delivery correctness on session completion.

---

## Phase 6: Docs + Rollout

### Task 6.1: Documentation updates

**File(s):**

- `docs/project/design/architecture/output-polling.md`
- `docs/project/design/architecture/outbox.md`
- `docs/` adapter docs where Telegram behavior is described

- [ ] Document the two-layer model: PTB limiter + TeleClaude output coalescer.
- [ ] Document tuning knobs and recommended defaults.
- [ ] Document known multi-process caveat and future Redis token-bucket path.

### Task 6.2: Safe rollout strategy

- [ ] Roll out behind feature flag.
- [ ] Start with conservative Telegram output budget and observe metrics.
- [ ] Enable Discord coalesce-only mode only after no-regression verification.

## Decision Record (Locked 2026-02-26)

1. `is_final` handling:
   - Use priority queue + next-slot dispatch.
   - Do not bypass scheduler invariants or output locks.
2. `active_emitting_sessions`:
   - Count sessions with pending payloads plus sessions that emitted in the last `10s`.
   - Apply light EMA smoothing to avoid cadence thrash during bursts.
3. Telegram reserve budget:
   - Default `reserve_mpm = 4` with `group_mpm = 20` and `output_budget_ratio = 0.8`.
   - Effective initial output budget target is `16 mpm` (tune from metrics after rollout).
