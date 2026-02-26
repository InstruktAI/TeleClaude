# Review Findings: adapter-output-qos-scheduler

## Critical

- None.

## Important

- Scheduler lifecycle cleanup is missing, so QoS worker tasks can outlive adapter shutdown.
  - Evidence: `UiAdapter` constructs `OutputScheduler` when QoS is enabled ([teleclaude/adapters/ui_adapter.py:104](../../teleclaude/adapters/ui_adapter.py#L104)), `OutputScheduler` exposes `stop()` ([teleclaude/adapters/qos/output_scheduler.py:91](../../teleclaude/adapters/qos/output_scheduler.py#L91)), but adapter `stop()` implementations do not call it ([teleclaude/adapters/telegram_adapter.py:925](../../teleclaude/adapters/telegram_adapter.py#L925), [teleclaude/adapters/discord_adapter.py:125](../../teleclaude/adapters/discord_adapter.py#L125), [teleclaude/adapters/whatsapp_adapter.py:65](../../teleclaude/adapters/whatsapp_adapter.py#L65)).
  - Impact: background QoS workers may continue dispatching after transport clients are closing/closed, creating post-shutdown send attempts and non-deterministic teardown behavior.
  - Fix: add a shared `UiAdapter` QoS shutdown hook and call it from each adapter `stop()` path.

- `coalesce_only` mode does not reliably coalesce under concurrent submits.
  - Evidence: non-strict modes always allow inline dispatch ([teleclaude/adapters/qos/output_scheduler.py:171](../../teleclaude/adapters/qos/output_scheduler.py#L171)), so payloads are popped immediately after enqueue ([teleclaude/adapters/qos/output_scheduler.py:139](../../teleclaude/adapters/qos/output_scheduler.py#L139)). This bypasses replacement of stale normal payloads ([teleclaude/adapters/qos/output_scheduler.py:153](../../teleclaude/adapters/qos/output_scheduler.py#L153)).
  - Reproduction: with `DiscordOutputPolicy(mode=coalesce_only)`, two concurrent `submit()` calls for one session execute both callbacks; `superseded_payloads` remains `0`.
  - Impact: default Discord rollout mode (`coalesce_only`) can still churn stale updates during overlap bursts instead of latest-only behavior.
  - Fix: for `coalesce_only`, block inline dispatch while a session is already dispatching and use queued/worker dispatch to enable replacement semantics.

## Suggestions

- Add unit coverage for `coalesce_only` concurrent semantics (assert stale payload replacement and supersede counters).
- Add adapter shutdown tests that verify QoS worker cancellation and no post-stop dispatch attempts.
- Live transport behavior (real Telegram/Discord flood-control conditions) remains unverified in this review environment.

## Paradigm-Fit Assessment

- Data flow: QoS logic is correctly isolated at adapter boundaries and does not leak transport concepts into core domain flows.
- Component reuse: implementation extends existing `UiAdapter` output pipeline instead of duplicating adapter-specific send/edit orchestration.
- Pattern consistency: policy + scheduler split aligns with the repository’s adapter abstraction patterns; no filesystem/data-layer bypasses detected.

## Manual Verification Evidence

- `make lint` passed (`ruff`, `pyright`, markdown/resource checks).
- Targeted behavioral tests passed:
  - `tests/unit/test_output_qos_scheduler.py`
  - `tests/unit/test_telegram_adapter_rate_limiter.py`
  - `tests/integration/test_telegram_output_qos_load.py`
  - `tests/unit/test_ui_adapter.py`
  - `tests/unit/test_threaded_output_updates.py`
- Additional manual reproduction (local script) confirmed the `coalesce_only` concurrency gap described above.
- Not manually verified against live Telegram/Discord APIs in this environment.

## Verdict

REQUEST CHANGES

## Fixes Applied

- Issue: Scheduler lifecycle cleanup is missing and QoS workers can outlive adapter shutdown.
  Fix: Added shared `UiAdapter._stop_output_scheduler()` and invoked it in Telegram/Discord/WhatsApp adapter `stop()` paths, plus shutdown-order unit tests.
  Commit: `9216e5bf489ea320f497ae7b2c57599f99143cbd`
- Issue: `coalesce_only` mode did not reliably coalesce during concurrent submits.
  Fix: Blocked inline dispatch in `coalesce_only` while the same session is already dispatching so queued replacement semantics can supersede stale payloads, plus concurrent regression coverage.
  Commit: `1c44cf08e40a848923b823349310a6477bc00542`
