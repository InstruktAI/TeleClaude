# Demo: chartest-core-next-machine

## Validation

```bash
. .venv/bin/activate
python - <<'PY'
from pathlib import Path

expected = {
    "test_build_gates.py",
    "test_create.py",
    "test_delivery.py",
    "test_git_ops.py",
    "test_icebox.py",
    "test_output_formatting.py",
    "test_prepare.py",
    "test_prepare_events.py",
    "test_prepare_steps.py",
    "test_roadmap.py",
    "test_slug_resolution.py",
    "test_state_io.py",
    "test_work.py",
    "test_worktrees.py",
}

test_dir = Path("tests/unit/core/next_machine")
actual = {path.name for path in test_dir.glob("test_*.py")}
missing = sorted(expected - actual)
assert not missing, f"Missing mapped tests: {missing}"
print(f"mapped characterization files present: {len(expected)}")
PY
```

```bash
. .venv/bin/activate
pytest \
  tests/unit/core/next_machine/test_build_gates.py \
  tests/unit/core/next_machine/test_create.py \
  tests/unit/core/next_machine/test_delivery.py \
  tests/unit/core/next_machine/test_git_ops.py \
  tests/unit/core/next_machine/test_icebox.py \
  tests/unit/core/next_machine/test_output_formatting.py \
  tests/unit/core/next_machine/test_prepare.py \
  tests/unit/core/next_machine/test_prepare_events.py \
  tests/unit/core/next_machine/test_prepare_steps.py \
  tests/unit/core/next_machine/test_roadmap.py \
  tests/unit/core/next_machine/test_slug_resolution.py \
  tests/unit/core/next_machine/test_state_io.py \
  tests/unit/core/next_machine/test_work.py \
  tests/unit/core/next_machine/test_worktrees.py \
  -q
```

## Guided Presentation

Start by running the mapping check block. Observe that all 14 planned next-machine modules now have a corresponding `tests/unit/core/next_machine/test_*.py` file.

Run the pytest block next. Observe that the new characterization suite passes as a batch and that it exercises the utility modules, phase-derivation helpers, and the `next_prepare` / `next_work` entry routing without modifying production code.

Point out that this demo is intentionally non-destructive: it verifies the safety net added for future refactors rather than changing runtime behavior.
