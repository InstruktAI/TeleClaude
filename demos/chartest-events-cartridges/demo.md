# Demo: chartest-events-cartridges

## Validation

```bash
uv run pytest tests/unit/events/cartridges/ -q --tb=short
```

```bash
uv run pytest tests/unit/events/cartridges/test_classification.py tests/unit/events/cartridges/test_trust.py tests/unit/events/cartridges/test_dedup.py -v --tb=short 2>&1 | tail -20
```

## Guided Presentation

Eight cartridges now have characterization test coverage. The test suite proves current
behavior at public boundaries, providing a safety net for future refactoring.

Run all cartridge tests to observe coverage:

```bash
uv run pytest tests/unit/events/cartridges/ -v 2>&1 | grep -E "PASSED|FAILED|ERROR" | head -40
```

Check the test count:

```bash
uv run pytest tests/unit/events/cartridges/ --collect-only -q 2>&1 | tail -5
```
