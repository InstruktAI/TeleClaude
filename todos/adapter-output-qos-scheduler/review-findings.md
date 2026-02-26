# Review Findings: adapter-output-qos-scheduler

**Review round:** 1
**Reviewer:** Claude (Opus 4.6)
**Scope:** `git diff $(git merge-base HEAD main)..HEAD` — 16 files changed

---

## Paradigm-Fit Assessment

- **Data flow:** The implementation properly extends the adapter hierarchy by overriding `send_output_update` and `send_threaded_output` at the concrete adapter level, routing through the QoS scheduler before delegating to the parent `UiAdapter`. No bypass of the existing data layer.
- **Component reuse:** The `OutputQoSScheduler` is a generic component parameterized by `QoSPolicy`, used by both Telegram and Discord adapters. No copy-paste duplication.
- **Pattern consistency:** Config parsing follows established patterns in `config/__init__.py` (dataclass + parser function + DEFAULT_CONFIG entry). Adapter lifecycle (start/stop) follows existing conventions.

---

## Critical

None.

---

## Important

### 1. `_compute_tick_s` does not implement `target_session_tick_s` — `min_session_tick_s` config is inert

**File:** `teleclaude/adapters/qos/output_scheduler.py:279-297`

The module docstring (line 15-21) and requirements FR4 both specify:

```
target_session_tick_s = ceil_to_ms(max(min_session_tick_s,
                                       global_tick_s * active_emitting_sessions),
                                   rounding_ms)
```

The actual `_compute_tick_s` implementation computes `global_tick_s` correctly but returns it directly without applying the `target_session_tick_s` formula. This means:

- **`min_session_tick_s`** (config key, QoSPolicy field, documented in `output-polling.md`) has no runtime effect — dead configuration that operators may attempt to tune.
- **`_ema_session_count`** is computed in `_dispatch_cycle` (line 193-194) but never feeds into tick computation — dead code path.

The implicit round-robin behavior in strict mode naturally achieves per-session scaling (`global_tick_s * N`), so the practical impact is limited. The gap is the absence of the `min_session_tick_s` floor enforcement. With defaults (min=3.0, tick=3.8), this is not observable. But with a higher `min_session_tick_s`, the floor would not be enforced.

**Recommendation:** Either implement `target_session_tick_s` in `_compute_tick_s`, or remove `min_session_tick_s` from config/policy/docs and document the design decision that round-robin provides implicit per-session scaling.

### 2. `_rr_sessions` and `_active_emitters` grow without bounds

**File:** `teleclaude/adapters/qos/output_scheduler.py:80-84, 163-164, 262`

Sessions are appended to `_rr_sessions` (line 164) and recorded in `_active_emitters` (line 262) but never pruned. For a long-running daemon:

- `_rr_sessions` accumulates every unique session_id that ever enqueued output. The filter at line 226 (`[s for s in self._rr_sessions if s in self._normal_slots]`) becomes increasingly expensive as the list grows, iterating over all historical sessions to find the few with pending slots.
- `_active_emitters` accumulates stale entries. `_compute_active_count` filters by window but does not remove expired entries.

For a daemon serving ~1000 unique sessions/day, after a month `_rr_sessions` would contain ~30K entries. The dispatch loop iterates this list every tick (3.8s in strict mode).

**Recommendation:** Add periodic pruning in `_dispatch_cycle` — remove sessions from `_rr_sessions` that have no pending slots and are outside the active emitter window. Prune `_active_emitters` of expired entries at the same time.

### 3. `stop()` silently drops pending payloads including priority/final payloads

**File:** `teleclaude/adapters/qos/output_scheduler.py:111-121`

When `stop()` is called, the background task is cancelled and all pending payloads (in `_normal_slots` and `_priority_queues`) are silently discarded. This includes `is_final=True` payloads that represent session completion messages (FR5).

During graceful adapter shutdown, a final-update payload may have been enqueued but not yet dispatched. The scheduler cancels without draining, losing the payload. The PTB rate limiter (layer 1) cannot compensate because the payload never reaches the transport layer.

**Recommendation:** In `stop()`, drain remaining priority payloads (at minimum) before cancelling the background task. Normal payloads can be safely dropped since the next output update would supersede them.

### 4. `_dispatch_loop` try-except scope is too narrow — unprotected lines can kill the background task permanently

**File:** `teleclaude/adapters/qos/output_scheduler.py:170-185`

In `_dispatch_loop`, `_compute_tick_s()` (line 173) and `_maybe_log_summary()` (line 185) execute outside the try-except block. If either raises an exception, the background task coroutine terminates. Once dead, no watchdog re-arms it — `start()` is only called once at adapter startup and never re-invoked. All subsequent `enqueue()` calls deposit payloads that are never consumed, with no error surfaced.

With default config this is unlikely (`_compute_tick_s` uses validated params, `_maybe_log_summary` is simple logging), but a misconfigured `rounding_ms=0` or a corrupted data structure would trigger permanent silent output freeze.

**Recommendation:** Widen the try-except to cover the full loop body, or add a dead-task check in `enqueue()` that logs a critical alert when payloads are deposited into a dead scheduler.

---

## Suggestions

### 5. Expose `mode` accessor on `OutputQoSScheduler`

**Files:** `teleclaude/adapters/telegram_adapter.py:1016`, `teleclaude/adapters/discord_adapter.py:859`

Both adapters access `self._qos_scheduler._policy.mode` directly — reaching two levels into private state. A `@property mode` or `is_active` helper on the scheduler would provide a cleaner contract and decouple adapters from the internal `_policy` structure.

### 6. `_dispatch_all_pending` session list construction is unnecessarily verbose

**File:** `teleclaude/adapters/qos/output_scheduler.py:204`

```python
pending_sessions = list(set(list(self._priority_queues.keys()) + list(self._normal_slots.keys())))
```

Could be simplified to:

```python
pending_sessions = list(set(self._priority_queues) | set(self._normal_slots))
```

### 7. Test coverage gaps worth addressing in follow-up

From the test analysis lane:

- No test for active emitter window expiry (verifying a stale session outside `active_emitter_window_s` is not counted).
- No test for multi-cycle round-robin ordering (the current test asserts `set` equality, not interleaving order).
- No adapter integration tests for the `off` mode bypass path (FR8/FR9 hinge on this).
- No test for `_dispatch_loop` exception resilience (verifying the loop continues after a `_dispatch_cycle` error).

---

## Deferral Validation

- **Task 5.2 (Integration/load checks):** Justified — requires a running daemon with active sessions and Telegram credentials. Not feasible in worktree.
- **Task 5.3 (Runtime validation):** Justified — requires `make restart` and live log observation. Post-merge validation path documented.

---

## Implementation Plan Verification

All non-deferred tasks (Phases 1-4, 5.1, 6.1, 6.2) are checked `[x]`. Deferred tasks (5.2, 5.3) are annotated with deferral reasons. Build section of quality-checklist.md is fully checked.

---

## Verdict: APPROVE

The core scheduler implementation is sound — coalescing, round-robin fairness, priority dispatch, dynamic cadence math, and adapter integration all follow correct patterns. The two-layer model (PTB rate limiter + TeleClaude scheduler) is well-designed. Config, policy, and adapter lifecycle follow established project conventions.

The 4 Important findings are real issues but not blockers for the initial rollout:

1. The `min_session_tick_s` gap has no practical impact with default configuration (3.0 < 3.8).
2. The memory growth is slow and proportional to unique sessions — manageable for current scale.
3. Payload loss on stop is an edge case during graceful shutdown that can be addressed in follow-up.
4. The try-except scope issue is unlikely with validated config but should be hardened.

These should be tracked for post-merge refinement.
