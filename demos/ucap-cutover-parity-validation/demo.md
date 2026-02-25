# Demo: ucap-cutover-parity-validation

## Validation

```bash
pytest -q tests/integration/test_multi_adapter_broadcasting.py
```

```bash
pytest -q \
  tests/unit/test_agent_activity_broadcast.py \
  tests/unit/test_threaded_output_updates.py
```

```bash
instrukt-ai-logs teleclaude --since 10m --grep "parity|cutover|rollback|send_output_update"
```

## Guided Presentation

1. Run three representative sessions visible in Web and TUI while Telegram/Discord receive mirrored updates.
2. For each session, show: no missing outputs and at most one duplicate output event.
3. Execute one rollback drill and show return to known-good behavior in logs.
4. Show absence of legacy bypass output paths and summarize residual risks.
