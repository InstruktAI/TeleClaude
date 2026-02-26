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

- [x] Add adapter QoS config structures and defaults (Telegram strict defaults, Discord/WhatsApp off/coalesce-only defaults).
- [x] Validate config parsing and backward compatibility with existing configs.

### Task 1.2: Define adapter policy contract

**File(s):**

- `teleclaude/adapters/qos/policy.py` (new)
- `teleclaude/adapters/qos/__init__.py` (new)

- [x] Define policy interface for:
  - coalescing strategy
  - budget computation
  - priority class mapping
  - optional per-adapter hard limits
- [x] Provide `TelegramOutputPolicy`, `DiscordOutputPolicy`, `WhatsAppOutputPolicy` placeholders.

---

## Phase 2: Scheduler Core

### Task 2.1: Build generic output scheduler

**File(s):**

- `teleclaude/adapters/qos/output_scheduler.py` (new)

- [x] Implement in-memory session queues keyed by `(adapter, session_id)`.
- [x] Implement latest-only payload replacement for normal priority events.
- [x] Implement priority lane for final/completion updates.
- [x] Implement fair dispatch (round-robin across active emitting sessions).
- [x] Implement tick computation helpers with 100ms rounding.

### Task 2.2: Add instrumentation

**File(s):**

- `teleclaude/adapters/qos/output_scheduler.py` (new)
- `teleclaude/services/monitoring_service.py` (if needed)

- [x] Emit metrics/log summaries:
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

- [x] Wire `Application.builder().rate_limiter(...)` using PTB supported limiter.
- [x] Add/install dependency support for PTB rate-limiter extra.
- [x] Ensure startup behavior is explicit if rate-limiter dependency is missing.

### Task 3.2: Route Telegram output through scheduler

**File(s):**

- `teleclaude/adapters/telegram_adapter.py`
- `teleclaude/adapters/ui_adapter.py` (minimal hook points only)
- `teleclaude/core/adapter_client.py` (only if required for clean hook insertion)

- [x] Apply scheduler to Telegram output methods for both:
  - `send_output_update`
  - `send_threaded_output`
- [x] Ensure non-blocking integration (shared fanout path remains free of sleep).
- [x] Ensure `is_final` flush behavior and deterministic cleanup on close.

### Task 3.3: Preserve existing fallback behavior

**File(s):**

- `teleclaude/adapters/telegram/message_ops.py`

- [x] Keep retry wrappers as fallback safety.
- [x] Remove only duplicated custom pacing logic (if superseded by scheduler + PTB limiter).

---

## Phase 4: Discord/WhatsApp Policy Rollout

### Task 4.1: Discord coalesce-only mode

**File(s):**

- `teleclaude/adapters/discord_adapter.py`
- `teleclaude/adapters/qos/policy.py`

- [x] Add opt-in coalesce-only mode for Discord output.
- [x] Keep strict caps off by default.

### Task 4.2: WhatsApp policy stub

**File(s):**

- `teleclaude/adapters/qos/policy.py`

- [x] Add policy stub and config slots for future adapter.
- [x] Document required external limit validation before enablement.

---

## Phase 5: Testing + Validation

### Task 5.1: Unit tests

**File(s):**

- `tests/unit/test_output_qos_scheduler.py` (new)
- `tests/unit/test_telegram_adapter_rate_limiter.py` (new)
- `tests/unit/test_threaded_output_updates.py` (update)
- `tests/unit/test_polling_coordinator.py` (update if integration points change)

- [x] Verify cadence math and rounding.
- [x] Verify coalescing (latest-only) and superseded drop accounting.
- [x] Verify fairness across many active sessions.
- [x] Verify final-priority flush behavior.
- [x] Verify threaded/non-threaded parity and no regression in output continuity.

### Task 5.2: Integration/load checks

**File(s):**

- `tests/integration/test_telegram_output_qos_load.py` (new, if feasible)
- `scripts/` load harness (optional)

- [ ] Simulate `N=20` active emitting sessions. **(deferred — requires live daemon)**
- [ ] Confirm sustained operation without runaway flood-control retries. **(deferred)**
- [ ] Confirm queue stabilization and bounded staleness. **(deferred)**

### Task 5.3: Runtime validation

- [ ] `make restart` **(deferred — requires live daemon, post-merge validation)**
- [ ] `make status` **(deferred)**
- [ ] `instrukt-ai-logs teleclaude --since 15m --grep "Output cadence summary|Rate limited|qos|scheduler"` **(deferred)**
- [ ] Validate final-message delivery correctness on session completion. **(deferred)**

---

## Phase 6: Docs + Rollout

### Task 6.1: Documentation updates

**File(s):**

- `docs/project/design/architecture/output-polling.md`
- `docs/project/design/architecture/outbox.md`
- `docs/` adapter docs where Telegram behavior is described

- [x] Document the two-layer model: PTB limiter + TeleClaude output coalescer.
- [x] Document tuning knobs and recommended defaults.
- [x] Document known multi-process caveat and future Redis token-bucket path.

### Task 6.2: Safe rollout strategy

- [x] Roll out behind feature flag (mode config: "off"/"coalesce_only"/"strict").
- [x] Start with conservative Telegram output budget and observe metrics (defaults: group_mpm=20, reserve=4, ratio=0.8 → 16 mpm).
- [x] Enable Discord coalesce-only mode only after no-regression verification (Discord defaults to coalesce_only).

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
