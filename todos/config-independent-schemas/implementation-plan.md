# Implementation Plan: config-independent-schemas

## Atomicity Assessment

**Verdict: ATOMIC.** One coherent behavior change — all pieces are tightly coupled
and independently unshippable. The input provides exact file paths and before/after
code, reducing discovery overhead. ~190 lines of change across 7 production files.

## Task Order

Tasks follow dependency order: schema foundation → loader → consumers → wiring → tests.
Each task references the spec tests it makes GREEN. The builder removes
`pytestmark = pytest.mark.xfail` from each test class as its first action per task.

---

### Task 1: [x] Break GlobalConfig inheritance and relocate checkout_root

**What:** In `teleclaude/config/schema.py`:

- Change `class GlobalConfig(ProjectConfig)` to `class GlobalConfig(BaseModel)`.
- Add explicit `model_config = ConfigDict(extra="allow")`.
- Keep only global-level fields: `people`, `subscriptions`, `interests`, `event_domains`.
- Add `checkout_root: str | None = None` as a declared field on GlobalConfig.
- Remove `checkout_root: str | None = None` from `GitConfig` (GitConfig becomes an
  empty-body model with `extra="allow"` — it still serves as a project-level git
  namespace).
- Keep existing `reject_disallowed_keys` on GlobalConfig that rejects person-only keys
  (`creds`, `notifications`, `timezone`). Do NOT add project-level keys to the
  disallowed set — existing global YAML files may contain them, and `extra="allow"`
  handles them silently (backward compat per constraint).
- Keep existing `parse_interests` field_validator.
- Add a `model_validator(mode="before")` on GlobalConfig that migrates
  `git.checkout_root` from the old YAML path to the top-level `checkout_root` field.
  This satisfies the backward-compat constraint for existing configs with
  `git.checkout_root`. Run this validator before `reject_disallowed_keys`.

**Why:** This is the core fix. The inheritance relationship is what causes GlobalConfig
to carry project-level fields, and it's what allows `load_project_config()` on a
PersonConfig file to blow up (PersonConfig has keys that ProjectConfig's
`reject_disallowed_keys` rejects). Breaking inheritance makes each schema independent.
Relocating `checkout_root` is coupled here because it's the only field that needs to
move between schemas.

**Verification:**

- `TestSchemaIndependence`: all 9 tests turn GREEN (inheritance checks, field exclusion,
  independent construction, key-rejection runtime behavior).
- `TestCheckoutRootRelocation`: `test_global_config_has_checkout_root_as_declared_field`
  and `test_project_git_config_no_longer_owns_checkout_root` turn GREEN.
- `TestCheckoutRootRelocation.test_backward_compat_checkout_root_on_project_config`
  turns GREEN.

**Referenced files:** `teleclaude/config/schema.py`

---

### Task 2: [x] Add AppConfig composed type

**What:** In `teleclaude/config/schema.py`:

- Add a frozen dataclass `AppConfig`:
  ```python
  @dataclass(frozen=True)
  class AppConfig:
      global_: GlobalConfig
      project: ProjectConfig | None = None
      person: PersonConfig | None = None
  ```
- Place it after the three config model definitions.
- Import `dataclass` from `dataclasses`.

**Why:** The composed type is the API contract between the entry-point loader and
consumers. It makes layer optionality explicit in the type system — global is always
present, project and person may be absent. Frozen ensures immutability after
construction, preventing accidental mutation of validated config.

**Verification:**

- `TestComposedConfig`: all 6 tests turn GREEN (existence, global always present,
  project/person optionality, immutability).

**Referenced files:** `teleclaude/config/schema.py`

---

### Task 3: [x] Add save_project_config to loader

**What:** In `teleclaude/config/loader.py`:

- Add `save_project_config(path: Path, config: ProjectConfig) -> None`.
- Implementation:
  1. Convert model to a serializable dict: `data = config.model_dump(mode="json", exclude_defaults=True)`.
  2. Write to a temp file (`.tmp` suffix in the same directory) using
     `yaml.safe_dump(data, f)`, then `f.flush()` + `os.fsync(f.fileno())`.
  3. Rename atomically: `os.replace(tmp_path, path)`.
  4. On any exception, delete the temp file before re-raising.
     This follows the same temp+replace atomicity guarantee as
     `config_handlers.py:_atomic_yaml_write`. `loader.py` already imports `yaml`
     (PyYAML) — use `yaml.safe_dump` for safe, tag-free serialization. The
     `model_dump(mode="json", ...)` step is required; passing the Pydantic model
     instance directly to `yaml.safe_dump` would produce Python-object-tagged YAML.
- Add import for `os` (standard library).

**Why:** The atomic save for project config doesn't exist. Global and person configs
have atomic save functions in `config_handlers.py`. Project config needs the same
pattern to prevent corruption on crash. Placing it in `loader.py` collocates it with
the load function and matches the test spec's import path.

**Verification:**

- `TestAtomicProjectConfigSave`: all 3 tests turn GREEN (function exists, round-trip
  write, atomicity on failure).

**Referenced files:** `teleclaude/config/loader.py`

---

### Task 4: [x] Add load_app_config to loader

**What:** In `teleclaude/config/loader.py`:

- Import `AppConfig` from schema.
- Add `load_app_config(workspace: Path) -> AppConfig`:
  ```
  1. Always load global config (from default path).
  2. Detect workspace type:
     a. Person workspace: workspace is under ~/.teleclaude/people/ →
        load person config from workspace/teleclaude.yml, project=None.
     b. Project workspace: workspace/teleclaude.yml exists and is NOT a
        person workspace → load project config from it.
     c. Unrecognized: no teleclaude.yml at workspace → return global-only
        (project=None, person=None). No fallback, no guessing.
  3. Return AppConfig(global_=global_config, project=project_config, person=person_config).
  ```
- Person workspace detection: check if `workspace` path is under
  `~/.teleclaude/people/` (use `Path.is_relative_to` or parents check).

**Why:** This is the single entry-point loader that replaces scattered
`load_project_config()` calls in the docs pipeline. It determines workspace type once
and returns the composed config. No caller needs to know the detection logic.

**Verification:**

- `TestPersonWorkspaceDocs`: `test_person_workspace_does_not_crash_on_docs_load`,
  `test_project_workspace_still_works`,
  `test_load_app_config_unrecognized_path_has_no_project` turn GREEN.

**Referenced files:** `teleclaude/config/loader.py`

---

### Task 5: [x] Update build_context_output to accept config parameter

**What:** In `teleclaude/context_selector.py`:

- Add `config: AppConfig | None = None` parameter to `build_context_output`.
- Import `AppConfig` from `teleclaude.config.schema`.
- When `config` is provided with a project layer:
  - Use `config.project.project_name or project_root.name` instead of calling
    `get_project_name(project_root)` (which internally calls `load_project_config`).
  - For domain resolution (when `domains` parameter is not explicitly provided):
    use `config.project.business.domains` instead of calling
    `_load_project_domains(project_root)`.
- When `config` is provided without a project layer (person workspace):
  - Use `project_root.name` for project name.
  - Use default domain config `{"software-development": project_root / "docs"}`.
- When `config` is NOT provided: existing behavior unchanged (backward compat for
  callers outside the docs pipeline).
- Add a pure helper `_resolve_domain_paths(domains: dict[str, str], project_root: Path) -> dict[str, Path]`
  that extracts the path-resolution logic from `_load_project_domains` without any
  config loading. Use it when config is provided. Keep `_load_project_domains` for the
  backward-compat path.

**Why:** This is the fix for the crash. By accepting config as a parameter, the
function no longer needs to call `load_project_config()` internally — which is what
crashes when `cwd` is a person workspace. The `config` parameter is optional so callers
outside the docs pipeline continue working without changes.

**Verification:**

- `TestInteriorLoadingElimination`: all 3 tests turn GREEN (signature inspection,
  load_project_config not called, get_project_name not called internally).
- `TestPersonWorkspaceDocs.test_person_workspace_returns_global_snippets` turns GREEN.

**Referenced files:** `teleclaude/context_selector.py`

---

### Task 6: [x] Wire docs CLI handler to use load_app_config

**What:** In `teleclaude/cli/telec/handlers/docs.py`:

- Import `load_app_config` from `teleclaude.config.loader`.
- In `_handle_docs_index`: call `config = load_app_config(Path.cwd())` before
  `build_context_output`, pass `config=config` to it.
- In `_handle_docs_get`: same pattern — call `load_app_config(Path.cwd())` and pass
  config through.

**Why:** This completes the entry-point wiring. The docs CLI handler is the production
caller of `build_context_output`. After this change, config is determined once at the
entry point and flows through — no interior loading.

**Verification:**

- Run `telec docs index` from both a project workspace and a person workspace path.
  Project workspace returns project + global snippets. Person workspace returns global
  snippets without crash.
- No direct spec test for this wiring, but it connects Tasks 4 and 5 into the
  end-to-end flow tested by `TestPersonWorkspaceDocs`.

**Referenced files:** `teleclaude/cli/telec/handlers/docs.py`

---

### Task 7: [x] Update git_repo_helper for checkout_root relocation

**What:** In `teleclaude/helpers/git_repo_helper.py`:

- In `_load_checkout_root()`, change `config.git.checkout_root` to
  `config.checkout_root` (GlobalConfig now has `checkout_root` as a top-level field).

**Why:** After Task 1, GlobalConfig no longer inherits `git` from ProjectConfig.
`checkout_root` is now a declared field on GlobalConfig. The helper must read from the
new location. The migration validator on GlobalConfig (Task 1) handles backward compat
for YAML files that still use `git.checkout_root`.

**Verification:**

- `TestCheckoutRootRelocation.test_load_checkout_root_reads_from_global_config`
  turns GREEN.

**Referenced files:** `teleclaude/helpers/git_repo_helper.py`

---

### Task 8: [x] Update existing tests affected by schema changes

**What:**

- `tests/unit/config/test_loader.py`:
  - `test_expands_env_vars_and_warns_about_unknown_keys`: After `checkout_root` is
    removed from `GitConfig`, loading a project config with `git.checkout_root` will
    produce an additional unknown-key warning on `root.git`. Update the
    `warning.call_args_list` assertion to include this new warning. The
    `result.git.checkout_root` attribute access still works via Pydantic v2's
    `extra="allow"` field access, so the value assertion is unchanged.
- `tests/unit/config/test_schema.py`: Verify no tests break. The existing tests
  exercise ProjectConfig validators, GlobalConfig rejection, and PersonConfig rejection
  — all of which are unchanged in behavior. No modifications expected.
- Remove the module-level `pytestmark = pytest.mark.xfail` from
  `tests/unit/config/test_config_independent_schemas.py` once all spec tests pass.

**Why:** Schema changes have downstream effects on existing characterization tests. The
unknown-key warning assertion is the only expected breakage — it's an assertion on
warning output, not on behavior.

**Verification:**

- Run `pytest tests/unit/config/ -x` — all tests pass.
- Run pre-commit hooks — tests, lint, typecheck all green.

**Referenced files:** `tests/unit/config/test_loader.py`,
`tests/unit/config/test_schema.py`,
`tests/unit/config/test_config_independent_schemas.py`

---

## Cross-cutting Verification

After all tasks:

1. `pytest tests/unit/config/test_config_independent_schemas.py` — all spec tests pass
   (no xfail markers remain).
2. `pytest tests/unit/config/` — all config tests pass.
3. Pre-commit hooks pass (full test suite, lint, typecheck).
4. Manual: `cd ~/.teleclaude/people/<name> && telec docs index` returns global snippets.
5. Manual: `cd <project-root> && telec docs index` works as before.
