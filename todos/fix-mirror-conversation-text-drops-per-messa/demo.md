# Demo: fix-mirror-conversation-text-drops-per-messa

## Validation

```bash
python -m pytest tests/unit/mirrors/test_generator.py -q
```

```bash
telec todo demo validate fix-mirror-conversation-text-drops-per-messa
```

## Guided Presentation

### Step 1 — Run the targeted regression tests

```bash
uv run pytest tests/unit/mirrors/test_generator.py -q
```

All eight tests should pass. The three `TestRenderConversation` tests prove:

- Messages with a real timestamp get the `[timestamp] Role: text` prefix.
- Messages with `timestamp=None` get no prefix — correct silent absence.
- Messages with `timestamp=""` (falsey non-None) now render `[] Role: text`
  instead of silently dropping the prefix. This is the bug that was fixed.

### Step 2 — Confirm the ingestion-layer fix

The previous silent path started in `_resolve_entry_timestamp`
(`teleclaude/utils/transcript/_tool_calls.py`): empty-string timestamps from
the JSON transcript were not rejected, so they reached `StructuredMessage.timestamp`
as `""`. After the fix, the check is `not isinstance(entry_ts_str, str) or not
entry_ts_str`, which normalises `""` to `None` at ingestion.

The renderer fix (`is not None` instead of falsey `if message.timestamp`) closes
the same silent path at the rendering boundary, so any non-None value — including
an unexpected empty string — is rendered explicitly rather than dropped.

### Step 3 — Confirm hooks stay green

```bash
pre-commit run --files teleclaude/mirrors/generator.py teleclaude/utils/transcript/_tool_calls.py tests/unit/mirrors/test_generator.py
```

All hooks must pass. This verifies the fix introduces no linting, typing, or
formatting regressions.
