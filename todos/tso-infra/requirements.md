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
2. Directory scaffold (git-tracked)
3. Conftest restructure (conservative)
4. CI enforcement script (reads from `pyproject.toml`)
5. Exemption configuration in `pyproject.toml`
6. Test structure policy doc snippet

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
- Each directory must contain at least a `conftest.py` stub to be tracked by git
  (git does not track empty directories). [inferred: without a tracked file, the
  scaffold vanishes on clone]

**Verification**: `find tests/unit -type d | sort` mirrors `find teleclaude -type d | grep -v __pycache__ | sort`. All scaffold directories survive a fresh `git clone`.

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
2. Load exemptions from `pyproject.toml` `[tool.test-mapping].exclude`. [inferred: follows
   Python ecosystem convention — ruff, pytest, mypy all use pyproject.toml for config]
3. For each source file not in the exclusion list, check whether a corresponding
   `tests/unit/<mirror-path>/test_<filename>.py` exists.
4. Print all gaps (unmapped, non-excluded files) to stdout.
5. Exit with code 1 if any gaps exist; exit 0 if all source files are mapped or excluded.

### Integration

- Add a `make check-test-mapping` target to the `Makefile` that runs
  `python tools/lint/test_mapping.py`. [inferred: follows existing Makefile pattern]
- Do NOT add it to `make lint` — it is expected to fail until workers complete their
  migration, so it must be a separate, opt-in target during the overhaul.

**Verification**: Running `python tools/lint/test_mapping.py` exits 1 and prints the
full gap list (expected at this stage). The script must pass ruff and pyright clean.
Running after workers complete migration exits 0.

---

## R5 — Exemption configuration in `pyproject.toml`

### Required format

```toml
[tool.test-mapping]
exclude = [
    "teleclaude/core/metadata.py",       # Pure Pydantic model, no logic
    "teleclaude/logging_config.py",       # Delegates to instrukt_ai_logging
]
```

Each excluded path must have an inline comment explaining why the file is exempt.

### Audit

Audit the existing `tests/ignored.md` exemptions against the actual file contents:
- Only exempt files with genuinely no testable logic (pure type definitions, config delegation).
- Files containing functions with branching, validation, parsing, or business rules are NOT
  exempt, regardless of what `tests/ignored.md` historically claimed.
- Remove stale entries for files that no longer exist.

`tests/ignored.md` remains as human documentation (deleted tests, known failures, context)
but is no longer the machine-parseable exemption source.

**Verification**: `python tools/lint/test_mapping.py` reads exclusions from `pyproject.toml`
and correctly excludes only legitimately trivial files.

---

## R6 — Test structure policy documentation

### Deliverable

Create `docs/global/software-development/policy/test-structure.md` codifying:
- The 1:1 file-to-test mapping rule and mirror convention.
- The `pyproject.toml` exemption format.
- Exemption validity criteria (genuinely no testable logic).
- CI enforcement via `make check-test-mapping`.
- Behavioral test contract standards (no hard-coded string assertions, max patches, descriptive names).

This doc snippet is the standard that the 8 module workers will build against. Without it,
they have tooling but no documented policy.

**Verification**: `telec docs index` lists the new snippet. Content covers all points above.

---

## Constraints (from input)

- No source files under `teleclaude/` are modified.
- Existing tests must still pass: `make test` passes before and after.
- Scaffold is additive — no existing tests moved; workers handle migration.
- Conftest changes must not break existing test imports.

---

## Definition of Done

- [ ] `tests/unit/` has all missing module directories, each git-tracked via conftest stub
- [ ] `make test` still passes (3300+ tests, 0 failures)
- [ ] `tools/lint/test_mapping.py` exists, reads from `pyproject.toml`, exits 1 with gap list
- [ ] `make check-test-mapping` target exists in `Makefile`
- [ ] `pyproject.toml` has `[tool.test-mapping].exclude` with only legitimately trivial files
- [ ] All new Python files pass `ruff check` and `pyright`
- [ ] No source files under `teleclaude/` modified
- [ ] `docs/global/software-development/policy/test-structure.md` exists and indexed
- [ ] `tests/ignored.md` stale exemptions identified (cleanup is module workers' scope)

---

## Inferences

- `[inferred]` No `__init__.py` files needed — existing `cli/` and `core/` subdirs operate without them under pytest rootdir mode. Conftest stubs serve as both fixture anchors and git-tracking markers.
- `[inferred]` `tools/lint/test_mapping.py` is the right location — follows the existing `tools/lint/guardrails.py` pattern.
- `[inferred]` `make check-test-mapping` should be a separate target, not part of `make lint`, because the enforcement is expected to fail until workers complete migration.
- `[inferred]` TUI helper functions should stay in `tests/conftest.py` because `test_tui_agent_status_cycle.py` imports `MockAPIClient` via `from tests.conftest import MockAPIClient`.
- `[inferred]` Exemptions belong in `pyproject.toml` — standard Python tooling convention. `tests/ignored.md` remains as human documentation but is not machine-parsed.
- `[inferred]` Most `tests/ignored.md` exemptions are stale — audit found 6 of 8 files contain real testable logic. Only `metadata.py` and `logging_config.py` are legitimately trivial. Correcting the false exemptions is module workers' scope; this todo establishes the correct exemption list.
