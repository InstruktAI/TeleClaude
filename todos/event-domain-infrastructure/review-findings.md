# Review Findings: event-domain-infrastructure

## Review Scope

Reviewed all changed files on branch `event-domain-infrastructure` against `main` (27 files, ~1976 insertions).

Lanes executed: code quality, principle violations, silent failure hunt, test coverage, demo verification, paradigm fit.

---

## Critical

### C1. `_caller_is_admin()` logic bug — checks if _any_ admin exists, not the current caller

**File:** `teleclaude/cli/cartridge_cli.py:39-59`

The function reads the session file but discards its content. It then iterates all people and returns `True` if any person has `role == "admin"` — regardless of who the current caller is. This means:
- If any admin is configured, all callers get admin privileges.
- If no admin is configured, no one gets admin privileges.

Neither behavior is correct. Combined with a broad `except Exception: return False` that silently defaults to non-admin on config failures, this is both a correctness and a security-adjacent defect.

**Fix:** Use the session identity to look up the specific caller's role, or acknowledge this as a placeholder with a documented TODO.

### C2. Bare `except Exception: continue` in `lifecycle.py` hides errors silently

**File:** `teleclaude_events/lifecycle.py:130-138` (`_find_cartridge_dir`) and `lifecycle.py:159-172` (`list_cartridges`)

Both locations catch any exception (YAML parse errors, permission errors, encoding errors, filesystem errors) and silently `continue` with **no logging**. This means:
- `remove()` reports "Cartridge not found" when the manifest is actually corrupt.
- `list` silently returns fewer results than actually exist.
- The operator has no signal that cartridges are being silently skipped.

**Fix:** Add `logger.warning(...)` before each `continue`, including the path and exception.

### C3. Personal pipeline exceptions silently discarded from `asyncio.gather`

**File:** `teleclaude_events/domain_pipeline.py:149-153`

`return_exceptions=True` captures exceptions as values, but the results are never inspected. If `PersonalPipeline.run` itself raises (not a cartridge inside it), the exception is completely invisible. Compare with domain pipeline exceptions at lines 141-146 which are logged.

**Fix:** Inspect gather results and log exceptions, matching the domain pipeline pattern.

### C4. `promote()` is structurally broken for personal→domain promotions

**File:** `teleclaude_events/lifecycle.py:89-119`

`_resolve_target_path(CartridgeScope.personal, target)` resolves to `personal_base / "members" / target / "cartridges"`. In `promote()`, `target_domain` (a domain name like `"sales"`) is passed as `target` for both `from_scope` and `to_scope`. When promoting from `personal` to `domain`, the source path becomes `members/sales/cartridges` instead of `members/{slugified_email}/cartridges`. The cartridge will never be found, and `CartridgeError("not found")` will always be raised.

The CLI at line 85 only exposes `--domain`, with no `--member` argument — so the source path cannot be constructed correctly even in principle.

**Fix:** Add a `source_member_id` parameter to `promote()` and a `--member` argument to the CLI's promote subcommand, used when `from_scope == CartridgeScope.personal`.

### C5. `exc_info=True` on a gathered exception instance produces no traceback

**File:** `teleclaude_events/domain_pipeline.py:143`

When `asyncio.gather(return_exceptions=True)` returns an exception as a value (not raised), `sys.exc_info()` is `(None, None, None)`. Passing `exc_info=True` logs no traceback — only the exception text from `%s`. The correct form is `exc_info=result` (passing the exception instance directly).

**Fix:** `logger.error("Domain pipeline '%s' failed: %s", name, result, exc_info=result)`

---

## Important

### I1. Imports inside function bodies — linting policy violation

**Files:**
- `teleclaude_events/lifecycle.py:131,151` — `import yaml` inside methods
- `teleclaude/cli/cartridge_cli.py:45` — `import os` inside function

Policy: "All imports at module top level." These should be hoisted.

### I2. `_get_lifecycle_manager() -> object` wrong return type

**File:** `teleclaude/cli/cartridge_cli.py:18`

Returns `object` instead of `LifecycleManager`, forcing `type: ignore[union-attr]` at every call site (lines 108, 121, 134, 156, 158, 167). The return type should be `LifecycleManager`.

### I3. Fragile field-by-field copy from `PipelineContext` to `DomainPipelineContext`

**File:** `teleclaude_events/domain_pipeline.py:39-48`

Each field of `base_context` is copied individually. If `PipelineContext` gains a new field, `DomainPipelineContext` will silently lose it. This is a coupling hazard.

**Fix:** Consider using `dataclasses.asdict(base_context)` or similar pattern to forward all base fields.

### I4. Inconsistent logging across new modules

Four new files use `logging.getLogger(__name__)` (standard library), while `cartridge_loader.py` uses `from instrukt_ai_logging import get_logger`. This may bypass structured logging features configured through the project logger.

**Files:** `domain_pipeline.py:7`, `personal_pipeline.py:5`, `lifecycle.py:4`, `startup.py:4`

### I5. Missing `exc_info=True` on error/warning logs in startup

**File:** `teleclaude_events/startup.py:53-58` (CartridgeError catch), `startup.py:78-79` (personal pipeline), `startup.py:80-81` (global config)

Error logs without `exc_info=True` lose the traceback. Production debugging of these failures requires stack traces.

### I6. `CartridgeConflictError` is dead code

**File:** `teleclaude_events/cartridge_manifest.py:37-38`

Defined but never raised. Output slot conflicts in `validate_pipeline` (`cartridge_loader.py:161-168`) produce a warning only. Either raise the exception to enforce uniqueness, or remove the dead class.

### I7. No dedicated tests for `personal_pipeline.py`

`PersonalPipeline.run` exception isolation and `load_personal_pipeline` rejection logic (personal=False, depends_on non-empty) have no dedicated test file. These behaviors are untested.

**Required tests:**
- Personal cartridge exception does not abort other personal cartridges
- Non-personal cartridge (personal=False) rejected
- Cartridge with `depends_on` rejected as non-leaf

### I8. Missing `exc_info` on domain pipeline startup log

**File:** `teleclaude_events/startup.py:53-58`

`logger.error("Failed to load domain pipeline '%s': %s — domain pipeline disabled", ...)` lacks `exc_info=True`. Different `CartridgeError` subclasses require different operator responses, and the traceback is needed to distinguish them.

### I9. `domain_registry.py` has zero test coverage

`_slugify_email` (regex on email → filesystem path), `cartridge_path_for` (two branches), `personal_path_for`, and `list_enabled` are all untested. A bug in `_slugify_email` silently routes personal cartridges to wrong directories.

### I10. `LoadedCartridge.process` typed as bare `Callable`

**File:** `teleclaude_events/cartridge_loader.py:30`

`process: Callable` without parameters is `Callable[..., Any]`. The full signature is known from the `Cartridge` protocol. Should be properly typed.

### I11. `sys.modules` entry is permanent, not "temporary" as comment claims

**File:** `teleclaude_events/cartridge_loader.py:57`

Comment says "Temporarily add path to sys.modules" but the entry is never removed on success — it's permanent for the process lifetime. Additionally, if two cartridges share the same `manifest.id`, the second silently overwrites the first in `sys.modules`.

---

## Suggestions

### S1. Defensive `getattr` on typed attributes

**File:** `teleclaude_events/startup.py:63-65`

`getattr(global_config, "people", [])` and `getattr(person, "email", None)` use defensive access on typed fields. Since `GlobalConfig.people: List[PersonEntry]` is explicitly typed, direct attribute access is correct.

### S2. Comment/variable name mismatch in domain pipeline

**File:** `teleclaude_events/domain_pipeline.py:63`

Comment says "Take first non-None result" but the loop takes the **last** non-None result. Variable is named `last_result` (correct), but the comment is misleading.

### S3. Fire-and-forget task doesn't handle `CancelledError`

**File:** `teleclaude_events/pipeline.py:70-83`

`asyncio.create_task` creates an unattached task. On shutdown, `CancelledError` (a `BaseException`) escapes the `except Exception` handler. Consider adding a done-callback or widening the catch for graceful shutdown.

### S4. Demo block 4 is shallow

**File:** `todos/event-domain-infrastructure/demo.md` block 4

Only instantiates an empty `DomainPipelineRunner()`. Doesn't exercise actual pipeline execution.

---

## Paradigm-Fit Assessment

The implementation follows existing codebase patterns well:
- Pydantic models for config schema (matches `schema.py` patterns)
- `importlib.util.spec_from_file_location` for dynamic module loading
- `asyncio.gather` with `return_exceptions=True` for parallel execution
- `Cartridge` Protocol interface preserved
- Config integration via `GlobalConfig` extension

No paradigm violations detected.

## Principle Violation Summary

| Principle | Violations |
|-----------|-----------|
| Fail Fast | C2 (silent continue), I5 (missing exc_info) |
| Boundary Purity | None |
| DIP | I4 (inconsistent logging layer) |
| SRP | None |
| Encapsulation | I3 (fragile field copy) |
| YAGNI | I6 (dead CartridgeConflictError class) |

---

## Fixes Applied

| Finding | Fix | Commit |
|---------|-----|--------|
| C1 | `_caller_is_admin()` rewired to use `get_session_field_sync(session_id, "human_role")` | b110761b3 |
| C2 | Added `logger.warning(path, exc)` before each `continue` in `_find_cartridge_dir` and `list_cartridges` | b110761b3 |
| C3 | Personal pipeline gather results inspected; exceptions logged with member_id and exc_info | b110761b3 |
| C4 | Added `source_member_id` param to `promote()`; `--member` arg added to CLI promote; ValueError when missing | b110761b3 |
| C5 | Changed `exc_info=True` to `exc_info=result` for gathered exception instances | b110761b3 |
| I1 | Hoisted `import yaml` and `import os` to module top level | b110761b3 |
| I2 | Fixed `_get_lifecycle_manager()` return type to `LifecycleManager` via TYPE_CHECKING | b110761b3 |
| I3 | Replaced fragile field-by-field copy with `fields(PipelineContext)` loop | b110761b3 |
| I4 | Replaced `logging.getLogger` with `instrukt_ai_logging.get_logger` in all new modules | b110761b3 |
| I5/I8 | Added `exc_info=True` to all error/warning logs in `startup.py` | b110761b3 |
| I6 | Removed dead `CartridgeConflictError` class | b110761b3 |
| I7 | Added `test_personal_pipeline.py` covering exception isolation, personal=False, depends_on rejection | 854d1eff4 |
| I9 | Added `test_domain_registry.py` covering `_slugify_email`, both `cartridge_path_for` branches, `personal_path_for`, `list_enabled` | 854d1eff4 |
| I10 | Typed `LoadedCartridge.process` as `Callable[[EventEnvelope, PipelineContext], Awaitable[...]]` | b110761b3 |
| I11 | Fixed misleading "Temporarily" comment; entry is permanent on success | b110761b3 |
| S1 | Replaced `getattr(global_config, "people", [])` etc. with direct attribute access | b110761b3 |
| S2 | Fixed comment "first non-None" → "last non-None" | b110761b3 |
| S3 | Added `CancelledError` handler to fire-and-forget task; re-raises for clean shutdown | b110761b3 |
| S4 | Skipped — demo block shallow, not blocking | — |

Tests: 2949 passed, 0 failed. Lint: clean (ruff, all checks passed).

---

## Verdict: APPROVE

All Critical and Important findings resolved. Suggestions S1–S3 addressed. S4 skipped (non-blocking demo).
Ready for re-review.
