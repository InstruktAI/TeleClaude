# Demo: chartest-events-cartridges

## Validation

```bash
./.venv/bin/python -m pytest tests/unit/events/cartridges/ -q --tb=short
```

```bash
./.venv/bin/python -m pytest tests/unit/events/cartridges/test_classification.py tests/unit/events/cartridges/test_trust.py tests/unit/events/cartridges/test_dedup.py -v --tb=short
```

## Guided Presentation

Eight cartridges now have characterization test coverage. The test suite proves current
behavior at public boundaries, providing a safety net for future refactoring.

Run all cartridge tests to observe coverage:

```bash
./.venv/bin/python -m pytest tests/unit/events/cartridges/ -v --tb=short
```

Check the test count:

```bash
./.venv/bin/python -m pytest tests/unit/events/cartridges/ --collect-only -q
```
