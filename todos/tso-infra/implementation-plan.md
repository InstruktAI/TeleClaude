# Implementation Plan: tso-infra

## Atomicity decision

**Verdict: atomic.** All six deliverables form one coherent behavior — "set up test
infrastructure before migration workers start." None are independently shippable:
the CI enforcement script depends on `ignored.md` format, both depend on the directory
scaffold, and the branch is the container for all. Total code changes: ~80 lines of new
Python, ~50 directory creates, minor Makefile and conftest additions. One builder
session.

**R6 trigger**: Audit of hard-coded string literals finds `"1.2.3"` used identically in
`tests/unit/test_deployment_channels.py`, `tests/unit/test_deployment_migration_runner.py`,
and `tests/unit/test_next_machine_demo.py` — three distinct files, same literal, version
fixture value. R6 is triggered; `tests/constants.py` is included below.

---

## Task 1 — Create feature branch

**What**: Create `feat/test-suite-overhaul` from current `main` HEAD.

```bash
git checkout -b feat/test-suite-overhaul
```

**Why**: All infrastructure changes ship on this branch so workers can branch from it.
The CI enforcement script evolves alongside worker migration commits.

**Referenced files**: none (git operation)

**Verification**: `git branch --list feat/test-suite-overhaul` returns the branch name.

---

## Task 2 — Create directory scaffold under tests/unit/

**What**: Create all missing module directories. No `__init__.py`, no placeholder files,
no test files. Use `mkdir -p` for nested paths.

Directories to create (relative to `tests/unit/`):

```
adapters/
adapters/discord/
adapters/qos/
adapters/telegram/
api/
channels/
chiptunes/
cli/tui/animations/
cli/tui/animations/sprites/
cli/tui/config_components/
cli/tui/utils/
cli/tui/widgets/
config/
core/integration/
core/migrations/
core/next_machine/
core/operations/
cron/
deployment/
entrypoints/
helpers/
helpers/youtube/
history/
hooks/
hooks/adapters/
hooks/normalizers/
hooks/utils/
install/
install/settings/
install/wrappers/
logs/
mcp/
memory/
memory/context/
mirrors/
notifications/
output_projection/
project_setup/
runtime/
services/
stt/
stt/backends/
tagging/
tools/
transport/
tts/
tts/backends/
types/
utils/
```

Existing directories to leave untouched: `cli/`, `core/`, `cli/tui/`, `cli/tui/views/`,
`test_signal/`, `test_teleclaude_events/`.

**Why**: No `__init__.py` files needed — existing `cli/` and `core/` subdirs operate
without them under pytest rootdir mode (`[inferred]`). Empty directories are valid
pytest collection roots; workers drop test files in without further scaffolding.

**Referenced files**: `tests/unit/` (directory tree), `teleclaude/` (directory tree)

**Verification**: `find tests/unit -type d | sort` output mirrors
`find teleclaude -type d | grep -v __pycache__ | sort` (excluding `teleclaude/` root).

---

## Task 3 — Update tests/conftest.py

**What**: Insert the comment line `# --- TUI fixtures ---` directly above
`def create_mock_session(` at line 101 of `tests/conftest.py`. No functions moved,
no imports changed.

**Why**: R3 preferred path — keep all TUI helpers in `tests/conftest.py` because
`tests/unit/test_tui_agent_status_cycle.py` imports `MockAPIClient` via
`from tests.conftest import MockAPIClient`. Moving or splitting requires a re-export
with no benefit. The section comment satisfies the labeling requirement at zero breakage
risk.

**Referenced files**: `tests/conftest.py`, `tests/unit/test_tui_agent_status_cycle.py`

**Verification**: `make test` passes (no import breakage).
`from tests.conftest import MockAPIClient` still resolves.

---

## Task 4 — Create module-level conftest stubs

**What**: Create the following files, each containing only a module docstring:

- `tests/unit/adapters/conftest.py` — `"""Module-level fixtures for adapters tests."""`
- `tests/unit/api/conftest.py` — `"""Module-level fixtures for api tests."""`
- `tests/unit/core/conftest.py` — `"""Module-level fixtures for core tests."""`
- `tests/unit/cli/conftest.py` — `"""Module-level fixtures for cli tests."""`
- `tests/unit/hooks/conftest.py` — `"""Module-level fixtures for hooks tests."""`
- `tests/unit/memory/conftest.py` — `"""Module-level fixtures for memory tests."""`

Before creating `tests/unit/core/conftest.py`, check whether it already exists. If it
does, append the docstring as a header comment instead of overwriting.

**Why**: Provides anchor points for workers to add module-specific fixtures without
modifying root `tests/conftest.py`. Docstring-only stubs are valid pytest conftest
files and produce no lint or collection errors.

**Referenced files**: `tests/unit/adapters/`, `tests/unit/api/`, `tests/unit/core/`,
`tests/unit/cli/`, `tests/unit/hooks/`, `tests/unit/memory/`

**Verification**: `find tests/unit -maxdepth 2 -name conftest.py` lists all 6 stubs.
`make test` passes with zero failures.

---

## Task 5 — Create tools/lint/test_mapping.py

**What**: New standalone script at `tools/lint/test_mapping.py`, following the
`tools/lint/guardrails.py` structural pattern.

```
from __future__ import annotations

import re
import sys
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    # ... logic below ...

if __name__ == "__main__":
    main()
```

Internal logic:
1. Collect all `.py` source files under `teleclaude/`, excluding `__init__.py` and any
   path containing `__pycache__`.
2. Parse `tests/ignored.md` with `re.compile(r"^### (teleclaude/.+\.py)$", re.MULTILINE)`
   to build a `set[str]` of exempt relative paths (e.g. `"teleclaude/constants.py"`).
3. For each source file (as a repo-root-relative posix path):
   - If path is in the exempt set, skip.
   - Compute mirrored test path: replace leading `teleclaude/` with `tests/unit/`, then
     replace the filename `<name>.py` with `test_<name>.py`.
   - Check whether `repo_root / mirrored_path` exists.
   - If not, record as a gap.
4. Print:
   ```
   MISSING TEST COVERAGE:
     teleclaude/foo.py → tests/unit/test_foo.py
     ...

   Total: N unmapped source files (see tests/ignored.md to exempt)
   ```
5. `sys.exit(1)` if gaps exist; `sys.exit(0)` if fully mapped or all exempt.

Type requirements: explicit `list[str]`, `set[str]`, `Path` throughout. No loose dicts,
no `Any`, no untyped functions. `ruff check` (pyproject.toml config) and `pyright`
(strict mode) must pass clean.

**Why**: Mirrors the `guardrails.py` structural pattern for consistency. Regex on
`### teleclaude/<path>` headings makes exemption lookup consistent with the format
enforced in Task 7 and robust to extra prose below each heading.

**Referenced files**: `tools/lint/guardrails.py`, `tests/ignored.md`,
`tools/lint/test_mapping.py` (new)

**Verification**: `python tools/lint/test_mapping.py` exits 1 (expected at this stage)
and prints the full gap list. `ruff check tools/lint/test_mapping.py` exits 0.
`pyright tools/lint/test_mapping.py` exits 0.

---

## Task 6 — Add make check-test-mapping target

**What**: Modify `Makefile`:

1. Add `check-test-mapping` to the `.PHONY` declaration line.
2. Add a help text echo line alongside the existing `make test`/`make lint` help lines:
   ```
   @echo "  make check-test-mapping   Check 1:1 source-to-test mapping (expected to fail during overhaul)"
   ```
3. Add the target:
   ```makefile
   check-test-mapping:
   	@python tools/lint/test_mapping.py
   ```

**Why**: Separate opt-in target, not part of `make lint`, because enforcement is
expected to fail until workers complete migration. Adding it to `make lint` would block
the pipeline for the entire overhaul duration (`[inferred]`).

**Referenced files**: `Makefile`

**Verification**: `make check-test-mapping` runs the script and exits 1 with the gap
list (expected behavior at this stage).

---

## Task 7 — Verify tests/ignored.md format compliance

**What**: Audit all `### teleclaude/…` headings in `tests/ignored.md`. The 9 current
entries already appear to match the required format (confirmed by reading the file).
Verify each has:
- Heading: `### teleclaude/<path/to/file.py>` (exact prefix, no trailing spaces)
- Followed (with or without one blank line) by: `**Reason**: <text>`

Fix any that don't comply. Preserve all content in "Deleted Test Files" and "Known
Failing Tests" sections — those sections don't use the `### teleclaude/<path>` format
and are not parsed by the CI script.

**Why**: The `test_mapping.py` regex `r"^### (teleclaude/.+\.py)$"` must match all
exempted entries. A malformed heading silently drops the exemption and produces a false
positive gap. Verify before running the CI script.

**Referenced files**: `tests/ignored.md`

**Verification**: After Task 5 is complete, `python tools/lint/test_mapping.py` correctly
excludes all 9 exempted files from the gap report (none appear in MISSING section).

---

## Task 8 — Create tests/constants.py

**What**: Create `tests/constants.py`:

```python
"""Shared test constants for repeated literal values across the test suite."""

TEST_VERSION = "1.2.3"
```

No imports, no fixtures. Constants only.

**Why**: R6 is triggered — `"1.2.3"` appears identically in 3 distinct test files:
`test_deployment_channels.py` (line 668), `test_deployment_migration_runner.py` (line 26),
and `test_next_machine_demo.py` (line 587). Tests importing it are workers' scope; this
PR only creates the file.

**Referenced files**: `tests/constants.py` (new),
`tests/unit/test_deployment_channels.py`,
`tests/unit/test_deployment_migration_runner.py`,
`tests/unit/test_next_machine_demo.py`

**Verification**: `ruff check tests/constants.py` exits 0. `pyright tests/constants.py`
exits 0. No test files modified.

---

## Task 9 — Create tests/unit/test_lint_test_mapping.py

**What**: Create `tests/unit/test_lint_test_mapping.py` with unit tests for the
`test_mapping.py` CI enforcement script, following the `test_lint_guardrails.py`
structural pattern (load module via `importlib.util.spec_from_file_location`).

For the tests to be unit-testable, extract the following helper functions from
`main()` during implementation:

- `_parse_exemptions(ignored_md: str) -> set[str]` — parses heading lines matching
  `r"^### (teleclaude/.+\.py)$"` from the file text, returns the set of relative paths.
- `_mirror_path(source_path: str) -> str` — replaces `teleclaude/` prefix with
  `tests/unit/` and renames `<name>.py` to `test_<name>.py`.

Tests to write (RED before GREEN):

1. `test_parse_exemptions_extracts_heading_paths` — provide markdown text with two
   `### teleclaude/<path>` headings and verify both are returned in the set.
2. `test_parse_exemptions_ignores_non_heading_lines` — verify prose lines and
   `### ` headings without `teleclaude/` prefix are not included.
3. `test_mirror_path_replaces_prefix_and_renames_file` — verify
   `"teleclaude/adapters/base_adapter.py"` → `"tests/unit/adapters/test_base_adapter.py"`.
4. `test_mirror_path_nested_module` — verify
   `"teleclaude/cli/tui/views/sessions.py"` → `"tests/unit/cli/tui/views/test_sessions.py"`.
5. `test_main_exits_nonzero_when_gaps_exist` — use `tmp_path` to create a minimal repo
   layout with one source file and no matching test; call `main()` via `pytest.raises(SystemExit)`
   and assert exit code 1.
6. `test_main_exits_zero_when_all_mapped` — same layout but with the corresponding test
   file present; assert exit code 0.

Type annotations explicit throughout; no `Any`.

**Why**: Codebase pattern is unambiguous — `test_lint_guardrails.py` tests `guardrails.py`
using module loading. Testing policy requires new functionality to have tests. Extracting
helpers makes `main()` unit-testable without file system mocks and follows single-responsibility.

**Referenced files**: `tests/unit/test_lint_guardrails.py`, `tools/lint/guardrails.py`,
`tools/lint/test_mapping.py` (new), `tests/unit/test_lint_test_mapping.py` (new)

**Verification**: All 6 new tests fail (RED) before `test_mapping.py` is written;
all pass (GREEN) after. `make test` shows ≥3453+6 tests, 0 failures.
`ruff check tests/unit/test_lint_test_mapping.py` exits 0.
`pyright tests/unit/test_lint_test_mapping.py` exits 0.

---

## Task 10 — Full suite verification and commit

**What**:
1. Run `make test` — confirm ≥3453 tests, 0 failures.
2. Run `ruff check tools/lint/test_mapping.py tests/constants.py tests/unit/test_lint_test_mapping.py` — confirm clean.
3. Run `pyright tools/lint/test_mapping.py tests/constants.py tests/unit/test_lint_test_mapping.py` — confirm clean.
4. Run `find tests/unit -type d | sort` — confirm scaffold completeness.
5. Run `telec todo demo validate tso-infra` — confirm demo exits 0.
6. Commit all changes on `feat/test-suite-overhaul`.

Commit message body:
```
feat(tso-infra): scaffold test infrastructure for test-suite-overhaul

- Create feat/test-suite-overhaul branch
- Add 46 missing tests/unit/ directories mirroring teleclaude/ tree
- Add module-level conftest stubs for adapters, api, core, cli, hooks, memory
- Label TUI section in tests/conftest.py (no code moved)
- Create tools/lint/test_mapping.py CI enforcement script (exits 1 until migration done)
- Add tests/unit/test_lint_test_mapping.py with 6 unit tests for test_mapping.py
- Add make check-test-mapping opt-in target
- Verify tests/ignored.md format compliance (all 9 entries conformant)
- Add tests/constants.py with TEST_VERSION constant (R6 triggered)
```

**Why**: A single atomic commit on the feature branch gives workers a clean branch
point. Pre-commit hooks validate lint, type check, and test before the commit lands.

**Referenced files**: all modified files above

**Verification**: `git log --oneline -1` shows the commit on `feat/test-suite-overhaul`.
`make test` shows ≥3453 tests, 0 failures.

---

## Review lane checklist

| Requirement | Task |
|---|---|
| Feature branch created | 1 |
| 28+ missing dirs created (46 total) | 2 |
| Existing dirs untouched | 2 (explicit guard) |
| `make test` passes | 10 |
| `test_mapping.py` exists, exits 1 with gap list | 5, 10 |
| `test_mapping.py` has unit tests (6 tests) | 9, 10 |
| `make check-test-mapping` target exists | 6 |
| `ignored.md` entries conform to format | 7 |
| Conftest stubs created for major modules | 4 |
| TUI helpers remain in `tests/conftest.py` | 3 |
| No `teleclaude/` source files modified | all (none touch teleclaude/) |
| All new Python passes ruff + pyright | 5, 8, 9, 10 |
| R6 triggered and addressed | 8 |
| Demo validated (`telec todo demo validate tso-infra`) | 10 |
