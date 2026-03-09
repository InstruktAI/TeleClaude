# Implementation Plan: tso-infra

## Atomicity decision

**Verdict: atomic.** All six deliverables form one coherent behavior — "set up test
infrastructure before migration workers start." None are independently shippable:
the CI enforcement script depends on `pyproject.toml` config, both depend on the directory
scaffold, and the branch is the container for all. Total code changes: ~70 lines of new
Python, ~47 conftest stubs, one doc snippet, minor Makefile additions. One builder
session.

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

**What**: Create all missing module directories mirroring `teleclaude/`. Each directory
gets a `conftest.py` stub containing only a module docstring — this ensures git tracks
the directory (git does not track empty directories).

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

Parent directories that need conftest stubs too (existing but previously empty):
`cli/tui/`, `cli/tui/views/`, `helpers/`, `install/`, `stt/`, `tts/`

Existing directories to leave untouched: `cli/`, `core/`, `test_signal/`,
`test_teleclaude_events/`.

**Why**: Git does not track empty directories. Without a tracked file, the scaffold
vanishes on clone. Conftest stubs serve as both fixture anchor points and git-tracking
markers.

**Referenced files**: `tests/unit/` (directory tree), `teleclaude/` (directory tree)

**Verification**: `find tests/unit -type d | sort` output mirrors
`find teleclaude -type d | grep -v __pycache__ | sort`. All directories contain a
`conftest.py`. `git clone` preserves the full scaffold.

---

## Task 3 — Update tests/conftest.py

**What**: Insert the comment line `# --- TUI fixtures ---` directly above
`def create_mock_session(` in `tests/conftest.py`. No functions moved, no imports changed.

**Why**: R3 preferred path — keep all TUI helpers in `tests/conftest.py` because
`tests/unit/test_tui_agent_status_cycle.py` imports `MockAPIClient` via
`from tests.conftest import MockAPIClient`. Moving or splitting requires a re-export
with no benefit. The section comment satisfies the labeling requirement at zero breakage
risk.

**Referenced files**: `tests/conftest.py`, `tests/unit/test_tui_agent_status_cycle.py`

**Verification**: `make test` passes (no import breakage).
`from tests.conftest import MockAPIClient` still resolves.

---

## Task 4 — Create tools/lint/test_mapping.py

**What**: New standalone script at `tools/lint/test_mapping.py`, following the
`tools/lint/guardrails.py` structural pattern.

Internal logic:
1. Collect all `.py` source files under `teleclaude/`, excluding `__init__.py` and any
   path containing `__pycache__`.
2. Load exclusions from `pyproject.toml` `[tool.test-mapping].exclude` using `tomllib`
   (stdlib, Python 3.11+).
3. For each source file (as a repo-root-relative posix path):
   - If path is in the exclusion set, skip.
   - Compute mirrored test path: replace leading `teleclaude/` with `tests/unit/`, then
     replace the filename `<name>.py` with `test_<name>.py`.
   - Check whether `repo_root / mirrored_path` exists.
   - If not, record as a gap.
4. Print gaps and exit 1 if any exist; exit 0 if fully mapped or excluded.

Exported helpers for testability:
- `_load_exclusions(repo_root: Path) -> set[str]` — reads `pyproject.toml`
- `_mirror_path(source_path: str) -> str` — computes test path

**Why**: `pyproject.toml` is the standard Python config location. `tomllib` is stdlib
since 3.11, requiring no external dependency.

**Referenced files**: `tools/lint/guardrails.py`, `pyproject.toml`,
`tools/lint/test_mapping.py` (new)

**Verification**: `python tools/lint/test_mapping.py` exits 1 (expected at this stage)
and prints the full gap list. `ruff check tools/lint/test_mapping.py` exits 0.
`pyright tools/lint/test_mapping.py` exits 0.

---

## Task 5 — Add make check-test-mapping target

**What**: Modify `Makefile`:

1. Add `check-test-mapping` to the `.PHONY` declaration line.
2. Add a help text echo line alongside the existing `make test`/`make lint` help lines.
3. Add the target:
   ```makefile
   check-test-mapping:
   	@python tools/lint/test_mapping.py
   ```

**Why**: Separate opt-in target, not part of `make lint`, because enforcement is
expected to fail until workers complete migration.

**Referenced files**: `Makefile`

**Verification**: `make check-test-mapping` runs the script and exits 1 with the gap
list (expected behavior at this stage).

---

## Task 6 — Configure exemptions in pyproject.toml

**What**: Add `[tool.test-mapping].exclude` section to `pyproject.toml` with only
legitimately trivial files:

```toml
[tool.test-mapping]
exclude = [
    "teleclaude/core/metadata.py",       # Pure Pydantic model, no logic
    "teleclaude/logging_config.py",       # Delegates to instrukt_ai_logging
]
```

**Why**: Audit of all prior `tests/ignored.md` exemptions found 6 of 8 were false or
stale. Only `metadata.py` (40 lines, pure Pydantic model) and `logging_config.py`
(29 lines, delegates to external lib) contain genuinely no testable logic.
`tests/ignored.md` remains as human documentation but is no longer machine-parsed.

**Referenced files**: `pyproject.toml`, `tests/ignored.md` (not modified, context only)

**Verification**: `python tools/lint/test_mapping.py` reads from `pyproject.toml` and
correctly skips only these 2 files.

---

## Task 7 — Create test structure policy doc snippet

**What**: Create `docs/global/software-development/policy/test-structure.md` with
frontmatter and content covering:
- 1:1 source-to-test mapping rule and mirror convention
- `pyproject.toml` exemption format
- Exemption validity criteria
- CI enforcement via `make check-test-mapping`
- Behavioral test contract standards

**Why**: R6 requirement. The 8 module workers need a documented policy to build against.
Without it, they have tooling but no standard.

**Referenced files**: `docs/global/software-development/policy/test-structure.md` (new)

**Verification**: `telec docs index` lists the new snippet. Content covers all required
points from R6.

---

## Task 8 — Create tests/unit/test_lint_test_mapping.py

**What**: Create unit tests for `test_mapping.py` following the `test_lint_guardrails.py`
structural pattern (load module via `importlib.util.spec_from_file_location`).

Tests (9 total):
1. `test_load_exclusions_reads_pyproject` — reads exclusions from pyproject.toml
2. `test_load_exclusions_empty_when_no_section` — graceful fallback when no config
3. `test_mirror_path_replaces_prefix_and_renames_file` — basic path transform
4. `test_mirror_path_nested_module` — deeply nested path transform
5. `test_mirror_path_top_level_module` — top-level module (no parent dir)
6. `test_main_exits_nonzero_when_gaps_exist` — exit 1 on unmapped files
7. `test_main_exits_2_when_source_dir_missing` — exit 2 on missing source dir
8. `test_main_exits_zero_when_all_mapped` — exit 0 when fully mapped
9. `test_main_excludes_files_in_pyproject` — exclusion flow end-to-end

Uses `_write_pyproject()` helper to create pyproject.toml in `tmp_path` fixtures.

**Referenced files**: `tests/unit/test_lint_guardrails.py`, `tools/lint/test_mapping.py`,
`tests/unit/test_lint_test_mapping.py` (new)

**Verification**: All 9 tests pass. `ruff check` and `pyright` clean.

---

## Task 9 — Full suite verification and commit

**What**:
1. Run `make test` — confirm ≥3338 tests, 0 failures.
2. Run `ruff check tools/lint/test_mapping.py tests/unit/test_lint_test_mapping.py` — clean.
3. Run `pyright tools/lint/test_mapping.py tests/unit/test_lint_test_mapping.py` — clean.
4. Verify all scaffold directories contain `conftest.py`.
5. Commit all changes.

**Why**: Single atomic commit gives workers a clean branch point.

**Referenced files**: all modified files above

**Verification**: `git log --oneline -1` shows the commit. `make test` passes.

---

## Review lane checklist

| Requirement | Task |
|---|---|
| Feature branch created | 1 |
| Directory scaffold with conftest stubs | 2 |
| Existing dirs untouched | 2 (explicit guard) |
| `make test` passes | 9 |
| `test_mapping.py` exists, reads pyproject.toml, exits 1 | 4, 9 |
| `test_mapping.py` has unit tests (9 tests) | 8, 9 |
| `make check-test-mapping` target exists | 5 |
| `pyproject.toml` has only legitimate exclusions | 6 |
| TUI helpers remain in `tests/conftest.py` | 3 |
| Doc snippet created | 7 |
| No `teleclaude/` source files modified | all (none touch teleclaude/) |
| All new Python passes ruff + pyright | 4, 8, 9 |

---

## Build Notes

All 9 tasks completed. Deliverables:

- [x] Task 1: `feat/test-suite-overhaul` branch created (tso-infra worktree)
- [x] Task 2: ~47 conftest stubs created across all scaffold directories
- [x] Task 3: TUI fixtures labeled in `tests/conftest.py` (section header present)
- [x] Task 4: `tools/lint/test_mapping.py` created with `_load_exclusions` (tomllib) and `_mirror_path`
- [x] Task 5: `make check-test-mapping` target added to Makefile
- [x] Task 6: `pyproject.toml` has `[tool.test-mapping].exclude` with 2 legitimate exclusions (audited from 8)
- [x] Task 7: `docs/global/software-development/policy/test-structure.md` created
- [x] Task 8: `tests/unit/test_lint_test_mapping.py` with 9 unit tests
- [x] Task 9: Full suite passes (3338 passed, 6 skipped); all new files pass ruff + pyright

**Changes from original plan**: Replaced `tests/ignored.md` regex parsing with `pyproject.toml` + `tomllib`.
Deleted `tests/constants.py` (dead code, imported by zero files). Reduced exemptions from 9 to 2 after audit.
Added doc snippet (R6). Added conftest stubs to all scaffold dirs for git tracking.
