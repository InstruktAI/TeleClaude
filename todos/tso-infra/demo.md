# Demo: tso-infra

## Validation

```bash
# Confirm feature branch exists
git branch --list feat/test-suite-overhaul
```

```bash
# Confirm directory scaffold mirrors teleclaude/ tree
diff \
  <(find tests/unit -type d | grep -v __pycache__ | sed 's|tests/unit/||' | sort) \
  <(find teleclaude -type d | grep -v __pycache__ | sed 's|teleclaude/||' | grep -v '^$' | sort)
```

```bash
# Confirm conftest stubs exist for major modules
find tests/unit -maxdepth 2 -name conftest.py | sort
```

```bash
# Confirm CI enforcement script is present and functional
python tools/lint/test_mapping.py; echo "Exit code: $?"
```

```bash
# Confirm make target exists
make check-test-mapping; echo "Exit code: $?"
```

```bash
# Confirm test suite still passes
make test
```

```bash
# Confirm new Python files pass lint and type check
ruff check tools/lint/test_mapping.py tests/constants.py
pyright tools/lint/test_mapping.py tests/constants.py
```

## Guided Presentation

Start on the `feat/test-suite-overhaul` branch.

**Step 1 — Branch**: Confirm the feature branch exists.

```bash
git branch --list feat/test-suite-overhaul
```

You should see `feat/test-suite-overhaul` listed. This is the branch all worker todos
will target during the migration phase.

**Step 2 — Directory scaffold**: Show the directory alignment.

```bash
find tests/unit -type d | grep -v __pycache__ | sort
```

Observe that `tests/unit/` now contains subdirectories for every module in
`teleclaude/`: `adapters/`, `adapters/discord/`, `api/`, `channels/`, `hooks/`, etc.
Previously only `cli/`, `core/`, `test_signal/`, and `test_teleclaude_events/` existed.
Workers can now place test files in the correct location without creating directories
first.

**Step 3 — Conftest stubs**: Show the new conftest files.

```bash
find tests/unit -maxdepth 2 -name conftest.py | sort
```

Six stubs appear under `adapters/`, `api/`, `core/`, `cli/`, `hooks/`, and `memory/`.
These are docstring-only anchor points. Workers populate them with module-specific
fixtures as they migrate tests.

**Step 4 — CI enforcement script**: Run the gap reporter.

```bash
python tools/lint/test_mapping.py
```

The script exits 1 and prints the full list of unmapped source files — this is the
expected behavior at this stage. The list shows exactly which files still need
corresponding test files in `tests/unit/`. Workers use this output to track migration
progress. Once all files are mapped or exempted in `tests/ignored.md`, the script exits
0 and the overhaul is complete.

**Step 5 — Make target**: Show the opt-in Makefile target.

```bash
make check-test-mapping
```

Same output as above — the target is a convenience wrapper. It is intentionally NOT
part of `make lint` so it doesn't block CI during the overhaul.

**Step 6 — Test suite unchanged**: Confirm no regression.

```bash
make test
```

All ≥3453 existing tests pass. The infrastructure is purely additive — no source files
touched, no existing test imports broken.
