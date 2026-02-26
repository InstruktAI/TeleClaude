# Demo: Adapter Output QoS Scheduler

## Goal

Show that adapter output QoS is active with strict Telegram pacing/coalescing, PTB limiter wiring, and load-stable coalescing behavior.

## 1) Verify scheduler and limiter behavior tests

```bash
TELECLAUDE_CONFIG_PATH=tests/integration/config.yml TELECLAUDE_ENV_PATH=tests/integration/.env \
  .venv/bin/pytest \
  tests/unit/test_output_qos_scheduler.py \
  tests/unit/test_telegram_adapter_rate_limiter.py \
  tests/integration/test_telegram_output_qos_load.py -q
```

Expected:

- All tests pass.
- Coverage includes cadence math, latest-only coalescing, high-priority queue jump, fairness, and load stabilization.

## 2) Show configured adapter QoS modes and Telegram defaults

```bash
TELECLAUDE_CONFIG_PATH=tests/integration/config.yml TELECLAUDE_ENV_PATH=tests/integration/.env \
  .venv/bin/python - <<'PY'
from teleclaude.config import config
print('telegram.enabled:', config.telegram.qos.enabled)
print('telegram.group_mpm:', config.telegram.qos.group_mpm)
print('telegram.output_budget_ratio:', config.telegram.qos.output_budget_ratio)
print('telegram.reserve_mpm:', config.telegram.qos.reserve_mpm)
print('discord.mode:', config.discord.qos.mode)
print('whatsapp.mode:', config.whatsapp.qos.mode)
PY
```

Expected:

- Telegram strict defaults print with enabled QoS parameters.
- Discord mode prints `coalesce_only`.
- WhatsApp mode prints `off`.

## 3) Verify broader adapter output regression suite

```bash
TELECLAUDE_CONFIG_PATH=tests/integration/config.yml TELECLAUDE_ENV_PATH=tests/integration/.env \
  .venv/bin/pytest \
  tests/unit/test_ui_adapter.py \
  tests/unit/test_telegram_adapter.py \
  tests/unit/test_adapter_client.py \
  tests/unit/test_threaded_output_updates.py -q
```

Expected:

- Existing output delivery behavior remains stable across threaded and non-threaded paths.
