# Requirements: tso-infra

Parent: test-suite-overhaul

## Problem

The test suite has no structural enforcement. `tests/unit/` contains ~240 flat test files
with only two module subdirectories (`cli/`, `core/`), while `teleclaude/` has 28+ module
directories with nested structure. Before workers can restructure module tests, the
infrastructure must exist.

## Scope

Six deliverables, all additive and non-destructive:

1. Feature branch
2. Directory scaffold
3. Conftest restructure (conservative)
4. CI enforcement script
5. `tests/ignored.md` machine-parseable format
6. Shared test constants (conditional)

---

## R1 — Feature branch

Create `feat/test-suite-overhaul` from the current `main` HEAD.

**Verification**: `git branch --list feat/test-suite-overhaul` returns the branch.

---

## R2 — Directory scaffold

Create `tests/unit/<module>/` directories mirroring the full `teleclaude/` tree.

### Required directories (currently missing)

All top-level modules: `adapters`, `api`, `channels`, `chiptunes`, `config`, `cron`,
`deployment`, `entrypoints`, `helpers`, `history`, `hooks`, `install`, `logs`, `mcp`,
`memory`, `mirrors`, `notifications`, `output_projection`, `project_setup`, `runtime`,
`services`, `stt`, `tagging`, `tools`, `transport`, `tts`, `types`, `utils`

Nested modules mirroring `teleclaude/`:
- `adapters/discord/`, `adapters/qos/`, `adapters/telegram/`
- `cli/tui/animations/`, `cli/tui/animations/sprites/`, `cli/tui/config_components/`,
  `cli/tui/utils/`, `cli/tui/widgets/`
- `core/integration/`, `core/migrations/`, `core/next_machine/`, `core/operations/`
- `helpers/youtube/`
- `hooks/adapters/`, `hooks/normalizers/`, `hooks/utils/`
- `install/settings/`, `install/wrappers/`
- `memory/context/`
- `stt/backends/`, `tts/backends/`

### Rules

- Existing directories (`cli/`, `core/`, `cli/tui/`, `cli/tui/views/`, `test_signal/`,
  `test_teleclaude_events/`) are untouched.
- No `__init__.py` files are created. [inferred: existing `cli/` and `core/` subdirs have
  no `__init__.py` and pytest resolves them correctly under rootdir mode]
- No test files are created. Workers create the actual test files.
- Each directory is created empty (no placeholder files needed).

**Verification**: `find tests/unit -type d | sort` mirrors `find teleclaude -type d | grep -v __pycache__ | sort` (excluding `teleclaude/__pycache__` dirs and the root).

---

## R3 — Conftest restructure (conservative)

**Constraint**: All existing test imports must remain valid. `test_tui_agent_status_cycle.py`
imports `MockAPIClient` directly via `from tests.conftest import MockAPIClient` — this import
path must remain resolvable after any changes.

### R3.1 — Audit

Identify which items in `tests/conftest.py` are TUI-specific vs. globally useful:

- **Global (keep in `tests/conftest.py`)**: `pytest_collection_modifyitems`, `_reset_event_bus`,
  `_isolate_tui_state`, `_isolate_test_environment`
- **TUI-specific**: `create_mock_session`, `create_mock_computer`, `create_mock_project`,
  `MockAPIClient`

### R3.2 — Optionally create `tests/unit/cli/tui/conftest.py`

**Preferred path (simpler)**: Keep TUI-specific helpers (`create_mock_session`,
`create_mock_computer`, `create_mock_project`, `MockAPIClient`) in `tests/conftest.py`;
add a docstring comment labeling the section "TUI fixtures". Do not create the new file.

**Fallback**: If keeping helpers in `tests/conftest.py` would introduce circular imports
or lint errors, move them to `tests/unit/cli/tui/conftest.py` and re-export them from
`tests/conftest.py`. [inferred: since that test imports via
`from tests.conftest import MockAPIClient`, keeping the re-export prevents breakage]

### R3.3 — Create module-level conftest stubs

Create empty (docstring-only) `tests/unit/<module>/conftest.py` stubs for the major modules
where workers will add module-specific fixtures. Modules requiring stubs: `adapters`, `api`,
`core`, `cli`, `hooks`, `memory`.

Workers will populate these as they migrate tests.

**Verification**: `make test` passes with zero failures after all conftest changes.
No lint errors introduced. `find tests/unit -maxdepth 2 -name conftest.py` lists stubs
for `adapters`, `api`, `core`, `cli`, `hooks`, `memory`.

---

## R4 — CI enforcement script

### Location

`tools/lint/test_mapping.py` — following the existing `tools/lint/guardrails.py` pattern.

### Behavior

1. Collect all `.py` source files under `teleclaude/` (excluding `__init__.py` and
   `__pycache__`).
2. Load exemptions from `tests/ignored.md` by parsing all `### teleclaude/<path>` headings.
3. For each source file not in the exemption list, check whether a corresponding
   `tests/unit/<mirror-path>/test_<filename>.py` exists.
4. Print all gaps (unmapped, non-exempt files) to stdout.
5. Exit with code 1 if any gaps exist; exit 0 if all source files are mapped or exempt.

### Integration

- Add a `make check-test-mapping` target to the `Makefile` that runs
  `python tools/lint/test_mapping.py`. [inferred: follows existing Makefile pattern]
- Do NOT add it to `make lint` — it is expected to fail until workers complete their
  migration, so it must be a separate, opt-in target during the overhaul.

### Output format

```
MISSING TEST COVERAGE:
  teleclaude/adapters/base_adapter.py → tests/unit/adapters/test_base_adapter.py
  teleclaude/api/auth.py              → tests/unit/api/test_auth.py
  ...

Total: 42 unmapped source files (see tests/ignored.md to exempt)
```

**Verification**: Running `python tools/lint/test_mapping.py` exits 1 and prints the
full gap list (expected at this stage). The script must pass ruff and pyright clean.
Running after workers complete migration exits 0.

---

## R5 — `tests/ignored.md` machine-parseable format

### Required format

Every file entry must conform to this pattern:

```markdown
### teleclaude/<path/to/file.py>

**Reason**: <single-line description>
```

- The heading is the canonical machine key: `### teleclaude/<relative-path>`.
- The `**Reason**: <text>` line immediately follows the heading (separated by one blank line
  is acceptable).
- Additional prose, bullet points, and coverage notes below the Reason line are preserved
  for human readability.

### Required changes

- Audit existing entries in `tests/ignored.md` for format compliance.
- Fix any headings that do not match `### teleclaude/<path>` exactly.
- Preserve all existing content, rationale, and the "Deleted Test Files" and
  "Known Failing Tests" sections (these do not need the `### teleclaude/<path>` format
  since they are not source-file exemptions).

**Verification**: `python tools/lint/test_mapping.py` correctly parses all exempted files
from `tests/ignored.md` without errors. The 8 existing `### teleclaude/…` entries are
all recognized and excluded from the gap report.

---

## R6 — Shared test constants (conditional)

**Trigger**: Only implement if the audit (during R3 or during codebase grounding) finds
≥3 distinct test files using identical hard-coded string literals for version strings,
config keys, error messages, or other non-behavioral values.

If triggered:
- Create `tests/constants.py` with the shared literals as module-level constants.
- Do not introduce fixtures here — constants only.
- Do not add it as a pytest fixture; tests import it directly.

If not triggered:
- Skip this deliverable. Do not create the file speculatively.

**Verification**: If created, `tests/constants.py` has no unused imports and passes lint.
No test files are modified in this PR (that is workers' scope).

---

## Constraints (from input)

- No source files under `teleclaude/` are modified.
- Existing tests must still pass: `make test` passes before and after.
- Scaffold is additive — no existing tests moved; workers handle migration.
- Conftest changes must not break existing test imports.

---

## Definition of Done

- [ ] `feat/test-suite-overhaul` branch exists
- [ ] `tests/unit/` has all 28+ missing module directories
- [ ] `make test` still passes (3453+ tests, 0 failures)
- [ ] `tools/lint/test_mapping.py` exists, runs, exits 1 with gap list
- [ ] `make check-test-mapping` target exists in `Makefile`
- [ ] `tests/ignored.md` entries all conform to `### teleclaude/<path>` + `**Reason**: <text>` format
- [ ] All new Python files pass `ruff check` and `pyright`
- [ ] No source files under `teleclaude/` modified
- [ ] Conftest stubs created for major modules

---

## Inferences

- `[inferred]` No `__init__.py` files needed in new scaffold directories — existing `cli/` and `core/` subdirs operate without them under pytest rootdir mode.
- `[inferred]` `tools/lint/test_mapping.py` is the right location — follows the existing `tools/lint/guardrails.py` pattern.
- `[inferred]` `make check-test-mapping` should be a separate target, not part of `make lint`, because the enforcement is expected to fail until workers complete migration.
- `[inferred]` TUI helper functions should be re-exported from `tests/conftest.py` (or left there) because `test_tui_agent_status_cycle.py` imports `MockAPIClient` via `from tests.conftest import MockAPIClient`.
- `[inferred]` Module conftest stubs needed for: `adapters`, `api`, `core`, `cli`, `hooks`, `memory` (where fixture sharing across module workers is most likely).
