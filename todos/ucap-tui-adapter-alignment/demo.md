# Demo: ucap-tui-adapter-alignment

## Validation

```bash
pytest -q \
  tests/unit/test_transcript_converter.py \
  tests/unit/test_threaded_output_updates.py
```

```bash
instrukt-ai-logs teleclaude --since 5m --grep "tui|send_output_update|OUTPUT_ROUTE"
```

## Guided Presentation

1. Start an active TUI session and submit a prompt.
2. Show incremental/final output updates arriving through canonical adapter output path.
3. Show logs that identify TUI lane on adapter-driven routing.
