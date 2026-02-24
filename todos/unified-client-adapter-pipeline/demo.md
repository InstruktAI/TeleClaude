# Demo: unified-client-adapter-pipeline

## Validation

```bash
pytest -q \
  tests/unit/test_adapter_client.py \
  tests/unit/test_agent_activity_broadcast.py \
  tests/unit/test_polling_coordinator.py
```

```bash
pytest -q \
  tests/unit/test_api_server.py \
  tests/unit/test_transcript_converter.py \
  tests/unit/test_threaded_output_updates.py
```

```bash
pytest -q tests/integration/test_multi_adapter_broadcasting.py
```

```bash
instrukt-ai-logs teleclaude --since 5m --grep "OUTPUT_ROUTE|send_output_update|stream"
```

## Guided Presentation

1. Open the same active session in Web and TUI. Send a prompt from Web.
   Observe that both clients show the same incremental/final output progression.
2. Send a prompt from TUI in the same session.
   Observe that provenance/origin routing still reflects correctly and output remains synchronized.
3. Confirm logs show adapter output routing activity (`send_output_update`) rather than a separate direct realtime bypass path.
4. Run the validation test blocks above and confirm all exit with code 0.
