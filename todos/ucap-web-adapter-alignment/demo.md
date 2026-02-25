# Demo: ucap-web-adapter-alignment

## Validation

```bash
pytest -q \
  tests/unit/test_api_server.py \
  tests/unit/test_threaded_output_updates.py
```

```bash
instrukt-ai-logs teleclaude --since 5m --grep "web|send_output_update|OUTPUT_ROUTE"
```

## Guided Presentation

1. Start an active Web session and submit a prompt.
2. Show Web receiving incremental/final updates from canonical adapter output path.
3. Show logs indicating adapter-driven send path, not direct Web bypass.
