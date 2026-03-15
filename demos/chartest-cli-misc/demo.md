# Demo: chartest-cli-misc

## Validation

```bash
# Run the new characterization tests and confirm all pass
pytest tests/unit/cli/ -q --tb=short 2>&1 | tail -5
```

```bash
# Confirm test count growth — at least 170 cli unit tests now exist
pytest tests/unit/cli/ --collect-only -q 2>&1 | tail -3
```

## Guided Presentation

The delivery adds 174 characterization tests across 10 CLI utility modules. Each test pins actual
behavior at a public boundary so that future refactors can't silently change it.

Run the suite to confirm all new tests are green:

```bash
pytest tests/unit/cli/ -v --tb=short 2>&1 | grep -E "(PASSED|FAILED|ERROR|passed|failed)" | tail -10
```

Spot-check a few representative behaviors:

- `SmartWatcher._is_sync_relevant` filters editor temp files and generated indexes
- `ToolAPIError` carries `status_code` and `is_timeout` flags
- `write_current_session_email` normalizes to lowercase and validates `@` presence
- `_deep_merge` performs non-destructive recursive YAML merging
