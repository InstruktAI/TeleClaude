# Demo: chartest-core-models

## Validation

```bash
make test 2>&1 | tail -5
```

```bash
make lint 2>&1 | tail -5
```

## Guided Presentation

The characterization tests for `teleclaude/core/models/` pin the current behavior of four core model modules at their public boundaries.

Run the new test files directly to see the behavioral specifications:

```bash
python -m pytest tests/unit/core/models/ -v 2>&1 | tail -30
```

These tests cover:

- `_adapter.py` — adapter metadata types, JSON serialization/deserialization, lazy initialization
- `_context.py` — command context dataclasses and their field defaults
- `_session.py` — session and recording models, frozen metadata, launch intents
- `_snapshot.py` — session snapshots, todo/project info, thinking modes
