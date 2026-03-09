# Demo: tso-infra — Test Suite Infrastructure

## What was built

Scaffold infrastructure for the test-suite-overhaul: directory scaffold with conftest
stubs, CI enforcement script reading from `pyproject.toml`, exemption audit (9 → 2),
test structure policy doc snippet, and a feature branch for workers to use.

---

## Section 1 — Feature branch exists

```bash
git branch --list tso-infra
```

Expected: `tso-infra` is listed.

---

## Section 2 — Directory scaffold mirrors teleclaude/

```bash
find tests/unit -type d | sort | wc -l
```

Expected: ≥55 directories (existing + new scaffold).

```bash
# Verify key new directories exist
for d in adapters api channels config cron deployment hooks install memory mirrors notifications output_projection runtime services stt tagging tools transport tts types utils; do
  [ -d "tests/unit/$d" ] && echo "OK: tests/unit/$d" || echo "MISSING: tests/unit/$d"
done
```

Expected: all 20 directories print `OK`.

---

## Section 3 — Conftest stubs track scaffold directories

```bash
# Every scaffold directory has a conftest.py
missing=0
for d in $(find tests/unit -type d | grep -v __pycache__); do
  if [ ! -f "$d/conftest.py" ] && [ "$d" != "tests/unit/test_signal" ] && [ "$d" != "tests/unit/test_teleclaude_events" ]; then
    echo "MISSING conftest: $d"
    missing=$((missing + 1))
  fi
done
[ "$missing" -eq 0 ] && echo "All scaffold directories have conftest.py stubs"
```

Expected: `All scaffold directories have conftest.py stubs`.

---

## Section 4 — CI enforcement script reads pyproject.toml

```bash
python -c "
import tomllib
from pathlib import Path
data = tomllib.loads(Path('pyproject.toml').read_text())
excl = data.get('tool', {}).get('test-mapping', {}).get('exclude', [])
print(f'Exclusions in pyproject.toml: {len(excl)}')
for e in excl:
    print(f'  {e}')
"
```

Expected: `Exclusions in pyproject.toml: 2` with `metadata.py` and `logging_config.py`.

```bash
python tools/lint/test_mapping.py 2>&1 | tail -3; echo "exit: $?"
```

Expected: prints `Total: N unmapped source files` and `exit: 1`.

---

## Section 5 — make check-test-mapping target exists

```bash
make check-test-mapping 2>&1 | tail -3; echo "exit: $?"
```

Expected: prints gap list and exits 1 (expected behavior during overhaul).

---

## Section 6 — Test structure policy doc snippet

```bash
[ -f docs/global/software-development/policy/test-structure.md ] && echo "Doc snippet exists" || echo "MISSING"
```

Expected: `Doc snippet exists`.

```bash
head -6 docs/global/software-development/policy/test-structure.md
```

Expected: frontmatter with `id: 'software-development/policy/test-structure'` and `type: 'policy'`.

---

## Section 7 — All new Python files lint clean

```bash
. .venv/bin/activate && ruff check tools/lint/test_mapping.py tests/unit/test_lint_test_mapping.py && echo "ruff: OK"
```

Expected: `ruff: OK`.

```bash
. .venv/bin/activate && pyright tools/lint/test_mapping.py tests/unit/test_lint_test_mapping.py 2>&1 | tail -3
```

Expected: `0 errors, 0 warnings, 0 informations`.

---

## Section 8 — Unit tests pass

```bash
. .venv/bin/activate && pytest tests/unit/test_lint_test_mapping.py --override-ini="addopts=-v --tb=short" 2>&1 | tail -5
```

Expected: `9 passed`.
