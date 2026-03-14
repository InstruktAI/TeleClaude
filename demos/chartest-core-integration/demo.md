# Demo: chartest-core-integration

## Validation

```bash
.venv/bin/python -m pytest tests/unit/core/integration/ -q --timeout=5 2>&1 | tail -5
```

## Guided Presentation

Run the characterization test suite to confirm all 12 integration modules are covered:

```bash
.venv/bin/python -m pytest tests/unit/core/integration/ -v --timeout=5 2>&1 | grep -E "PASSED|FAILED|ERROR|passed|failed" | tail -20
```

Confirm test count and zero failures:

```bash
.venv/bin/python -m pytest tests/unit/core/integration/ --co -q --timeout=5 2>&1 | tail -5
```
