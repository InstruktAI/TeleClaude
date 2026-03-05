# Review Findings: slug-helper

## Verdict: REQUEST CHANGES

---

## Critical

### 1. `_handle_todo_dump` stale slug in event payload and print output

**File:** `teleclaude/cli/telec.py:2259-2260, 2268, 2270`

After `create_todo_skeleton` returns, the caller's `slug` variable still holds the original value. When collision resolution renames `my-slug` to `my-slug-2`, four lines use the stale `slug`:

- Line 2259: `description=f"Todo dumped: {slug}"` — event description has wrong slug
- Line 2260: `payload={"slug": slug, ...}` — event payload has wrong slug
- Line 2268: `f"Dumped todo: todos/{slug}/"` — print output has wrong path
- Line 2270: `f"Dumped todo: todos/{slug}/"` — same in fallback print

The `input.md` heading (line 2240) was correctly fixed to use `todo_dir.name`, but the event and print lines were missed.

The requirements Risks section explicitly called out this exact scenario:
> "callers that use the original `slug` variable after calling skeleton functions must update to use `todo_dir.name` instead"

The implementation plan Task 2.3 marks this as done, but the fix is incomplete.

**Fix:** Add `slug = todo_dir.name` after line 2233 (same pattern as `_handle_bugs_report` at line 2946), then all subsequent references are correct.

**Principle violated:** Fail Fast / Contract fidelity — the event system receives a slug that doesn't match the filesystem, silently corrupting downstream automation.

---

## Important

_None._

---

## Suggestions

### 1. `validate_slug` void return requires callers to strip separately

**File:** `teleclaude/slug.py:11-17`, `teleclaude/todo_scaffold.py:72-73, 126-127, 173-174`

`validate_slug` strips whitespace internally for its checks but returns `None`. All three callers in `todo_scaffold.py` must call `slug = slug.strip()` on the next line. If a future caller forgets the strip, a whitespace-padded slug passes validation but creates a directory with whitespace in the name.

Consider changing `validate_slug` to return the stripped slug: `slug = validate_slug(slug)`.

### 2. `normalize_slug` empty result produces confusing error in `_handle_bugs_report`

**File:** `teleclaude/cli/telec.py:2930-2934`

When description contains only non-alphanumeric chars, `normalize_slug` returns `""`, producing `slug = "fix-"` which fails `validate_slug` with a misleading "Invalid slug" error. This is pre-existing behavior (identical to the old inline regex), but now that there's a shared module, an explicit empty-check with a clearer message would be a nice improvement.

### 3. TUI does not notify user when collision resolution renames their slug

**File:** `teleclaude/cli/tui/views/preparation.py:774-797`

When a user types `my-feature` in the TUI modal and it collides, the todo is created as `my-feature-2` without an explicit notification. The editor title bar shows the correct name, but a toast notification like `"Slug renamed to 'my-feature-2' ('my-feature' already exists)"` would be clearer.

### 4. Unrelated test assertion fixes included in branch

**Files:** `tests/integration/test_integrator_wiring.py`, `tests/unit/test_next_machine_hitl.py`, `tests/unit/test_next_machine_state_deps.py`, `tests/unit/test_tab_bar_edge.py`

Four test files were updated to fix stale assertions unrelated to slug-helper (e.g., `"deployment.started"` → `"telec todo integrate"`, tab bar color expectation). These are correct fixes needed to get `make test` green on the branch, but add noise to the diff. Acceptable.

### 5. Test invariant: `normalize_slug` output validity not asserted

**File:** `tests/unit/test_slug.py`

No test asserts that `SLUG_PATTERN.match(normalize_slug(input))` holds for all non-empty outputs. A parametrized invariant test would lock this contract against future regex changes.

---

## Paradigm-Fit Assessment

- **Data flow:** Correct. The new module follows the established pattern — pure functions, no side effects, imported by callers at the boundaries.
- **Component reuse:** Correct. No copy-paste — the inline logic was extracted to a shared module and callers delegate.
- **Pattern consistency:** Correct. The module structure, naming, and import style match adjacent code (`content_scaffold.py`, `todo_scaffold.py`).

## Principle Violation Hunt

**Checked categories:** Fallback/silent-degradation, Fail Fast, DIP, Coupling, SRP, YAGNI/KISS, Encapsulation, Immutability.

- **Fallback:** No unjustified fallbacks in changed code. `_derive_slug`'s `or "dump"` fallback is justified (UX requires a folder name).
- **DIP:** Clean. Core module (`slug.py`) has no adapter dependencies. Callers import from core.
- **SRP:** Clean. `slug.py` does one thing — slug operations. Each function has a single responsibility.
- **YAGNI/KISS:** Clean. No over-engineering. Three focused functions, no unnecessary abstractions.
- **Fail Fast:** One violation — the stale slug in `_handle_todo_dump` (Critical finding #1). The event system receives incorrect data without any validation.
- **Coupling:** Clean. No deep chains, no god-object patterns.

## Zero-Finding Justification (for Important)

No Important findings because:
1. **Paradigm fit verified:** Module structure, import patterns, and naming conventions all match established patterns.
2. **Requirements traced:** All 7 success criteria are met (module exists, callers wired, no duplicate logic, collision behavior changed, tests pass, new tests added, make test/lint pass).
3. **Copy-paste checked:** No duplication found in changed code. The `blocked_followup.py` duplicate is explicitly out of scope per requirements.
4. **The only actionable issue is a missed desync fix** in `_handle_todo_dump`, which is Critical because it corrupts event data.

## Demo Artifact Review

`demos/slug-helper/demo.md` has 4 executable bash blocks:
1. Import verification — confirms module exports exist. Valid.
2. SLUG_PATTERN uniqueness check — confirms no duplicate definitions. Valid.
3. Inline normalization absence check — confirms telec.py is clean. Valid.
4. `make test` — validates test suite. Valid.

The guided presentation accurately describes the implementation. No fabricated output. No flags or commands that don't exist.
