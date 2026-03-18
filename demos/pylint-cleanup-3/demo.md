# Demo: pylint-cleanup-3

## Validation

```bash
pylint teleclaude/adapters/telegram teleclaude/adapters/ui
```

```bash
pytest -q \
  tests/unit/adapters/telegram/test_message_ops.py \
  tests/unit/adapters/telegram/test_callback_handlers.py \
  tests/unit/adapters/telegram/test_input_handlers.py \
  tests/unit/adapters/telegram/test_private_handlers.py \
  tests/unit/adapters/ui/test_threaded_output.py \
  tests/unit/adapters/ui/test_output_delivery.py
```

## Guided Presentation

Run the `pylint` block first. The expected result is exit code `0` with no violations across
`teleclaude/adapters/telegram` and `teleclaude/adapters/ui`.

Run the `pytest` block next. The expected result is the adapter-focused regression suite passing,
showing that the lint cleanup preserved existing Telegram and UI adapter behavior.
