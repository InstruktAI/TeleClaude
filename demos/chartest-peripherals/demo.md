# Demo: chartest-peripherals

## Validation

```bash
TEST_FILES="$(python - <<'PY'
from pathlib import Path

req = Path('todos/chartest-peripherals/requirements.md').read_text(encoding='utf-8').splitlines()
tests: list[str] = []
for line in req:
    if line.startswith('- `teleclaude/'):
        src = line.split('`')[1]
        rel = src.removeprefix('teleclaude/').removesuffix('.py')
        parts = rel.split('/')
        tests.append(str(Path('tests/unit').joinpath(*parts[:-1], f'test_{parts[-1]}.py')))
print(' '.join(tests))
PY
)"
.venv/bin/pytest $TEST_FILES -q
```

```bash
python - <<'PY'
from pathlib import Path

req = Path('todos/chartest-peripherals/requirements.md').read_text(encoding='utf-8').splitlines()
count = 0
for line in req:
    if line.startswith('- `teleclaude/'):
        count += 1
print({'required_test_files': count})
PY
```

## Guided Presentation

Run the validation block to execute the full `chartest-peripherals` characterization batch.

Observe that pytest collects and passes the full mapped suite for the peripheral modules. This demonstrates the 1:1 source-to-test mapping and proves the characterization coverage is executable, not just present on disk.

Run the second block to show the expected mapping cardinality from the requirements file. The count should match the delivered batch and gives the reviewer a quick cross-check against the todo scope.
