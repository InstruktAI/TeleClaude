# Demo: pylint-cleanup-2

## Validation

```bash
pylint teleclaude/adapters/discord teleclaude/adapters/qos
```

```bash
pytest tests/unit/adapters/discord tests/unit/adapters/qos
```

## Guided Presentation

Run the assigned-path pylint command and observe that it exits cleanly with no remaining violations in
`teleclaude/adapters/discord` and `teleclaude/adapters/qos`.

Run the focused Discord and QoS unit tests and observe that the adapter behavior still passes after the lint-only
cleanup.
