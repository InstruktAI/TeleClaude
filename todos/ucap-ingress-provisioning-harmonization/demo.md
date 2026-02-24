# Demo: ucap-ingress-provisioning-harmonization

## Validation

```bash
pytest -q \
  tests/unit/test_command_mapper.py \
  tests/unit/test_command_handlers.py \
  tests/unit/test_adapter_client.py \
  tests/unit/test_adapter_client_handlers.py
```

```bash
pytest -q \
  tests/unit/test_telegram_adapter.py \
  tests/unit/test_discord_adapter.py \
  tests/integration/test_multi_adapter_broadcasting.py
```

```bash
make lint
```

```bash
instrukt-ai-logs teleclaude --since 10m --grep "ROUTING|ensure_channel|last_input_origin|send_user_input_reflection"
```

## Guided Presentation

1. Start or reuse a live session visible in at least two adapters (for example TUI + Telegram or Web + Discord).
2. Submit a user message from adapter A and confirm reflected input appears in non-source adapters with correct actor attribution.
3. Submit the next user message from adapter B and confirm response routing/provenance follows the new origin (no stale-origin behavior).
4. Trigger a path that requires UI channel verification and confirm no duplicate/missing channel side effects are observed.
5. Run the validation command blocks and confirm all exit with code 0.
6. Check logs for ingress/provisioning route signals and confirm they reference expected adapter lanes and session IDs.
