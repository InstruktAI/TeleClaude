# Review Findings: telec-config-interactive

**Review round:** 1
**Branch:** telec-config-interactive
**Commit:** 4c502dcb

---

## Critical

### C1: Import policy violations — function-scoped imports

**Policy:** All imports at module top level (linting-requirements rule 3).

| File                                | Line          | Import          |
| ----------------------------------- | ------------- | --------------- |
| `teleclaude/cli/config_menu.py`     | 196, 225, 468 | `import os`     |
| `teleclaude/cli/onboard_wizard.py`  | 244           | `import os`     |
| `teleclaude/cli/config_handlers.py` | 213           | `import shutil` |

**Fix:** Move all to module-level imports.

### C2: Type safety — `model_class=type(None)` violates declared type

**File:** `teleclaude/cli/config_handlers.py:48,417`

`ConfigArea.model_class` is typed `type[BaseModel]` but line 417 assigns `type(None)` (which is `NoneType`, not a `BaseModel` subclass). Will fail strict mypy.

**Fix:** Change field to `model_class: type[BaseModel] | None` and pass `None`.

### C3: Unbounded recursion in `_prompt_value`

**File:** `teleclaude/cli/config_menu.py:85-87`

When user enters empty on a required field, the function recurses with no depth bound. Repeated empty input hits `RecursionError`.

```python
if not raw and required:
    print(f"  {_RED}Value is required.{_RESET}")
    return _prompt_value(label, current, required)  # unbounded
```

**Fix:** Replace recursion with a `while True` loop.

### C4: Cross-module private imports

**File:** `teleclaude/cli/onboard_wizard.py:20-33`

Imports 12 underscore-prefixed private names (`_BOLD`, `_DIM`, `_print_header`, `_prompt_confirm`, etc.) from `config_menu.py`. This couples internals across modules and makes refactoring brittle.

**Fix:** Extract shared formatting constants and prompt utilities into a public module (e.g., `teleclaude/cli/prompt_utils.py`) with public names. Both `config_menu.py` and `onboard_wizard.py` import from there.

---

## Important

### I1: `category` field should use `Literal` type

**File:** `teleclaude/cli/config_handlers.py:46`

`category: str` is documented as `"adapter" | "people" | "notifications" | "environment"` but typed as bare `str`. Project convention uses `Literal` for constrained string domains (cf. `schema.py:10`). Typos like `"adapters"` pass type checking silently.

**Fix:** `category: Literal["adapter", "people", "notifications", "environment"]`

### I2: Overly broad exception catch

**File:** `teleclaude/cli/config_menu.py:460`

```python
except (ValueError, IndexError, Exception):
    continue
```

`Exception` subsumes the other two. This silently swallows all errors including unexpected bugs.

**Fix:** Catch only `(ValueError, IndexError)` and log or display the error.

### I3: Bare `except Exception` blocks across multiple locations

**Files:** `config_menu.py:291,333,372,392,418,446` and `onboard_wizard.py:68,201,219,236`

Multiple bare `except Exception` catches that print a generic message or silently continue. Violates fail-fast principle and hides real errors.

**Fix:** Catch specific expected exceptions (`ValidationError`, `FileNotFoundError`, `ValueError`). For truly unknown errors, at minimum log with `logger.exception()`.

### I4: Redundant imports in `_step_environment`

**File:** `teleclaude/cli/onboard_wizard.py:244-246`

`import os` is function-scoped (C1 duplicate), and `get_required_env_vars` is re-imported despite being available at module level (line 12-19 already imports it from config_handlers).

**Fix:** Remove both; use the module-level `os` import and the existing `get_required_env_vars` import.

---

## Suggestions

### S1: Missing error path test coverage

No tests for: atomic write failures (permissions), invalid YAML schema loading, `remove_person` when person not found (although `add_person` duplicate is tested). Consider adding targeted error path tests.

### S2: Missing `telec onboard` non-tty test

`_handle_config([])` has a non-tty test (`test_telec_config_non_tty_fails`), but `_handle_onboard([])` does not, despite having the same guard at `telec.py:961`.

### S3: No test for `discover_config_areas` configured state

Test only checks area names exist, not whether `configured` flag is correctly set when a person has adapter credentials.

### S4: No menu flow integration tests

Only the main menu rendering is tested (immediately quits). No tests exercise adapter detail, people edit, or notifications flows with mocked input sequences.

---

## Verdict: REQUEST CHANGES

4 critical + 4 important findings. The critical issues (import policy, type contract, recursion bug, cross-module coupling) must be resolved before merge.
