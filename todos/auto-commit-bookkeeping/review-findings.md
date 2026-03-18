# Review Findings: auto-commit-bookkeeping

**Ad-hoc review (via from-main)** — scope and demo lanes skipped per procedure.

---

## Round 1 (prior review)

### Previously Reported (all resolved)

1. **`commit_bookkeeping_to_main` had zero test coverage** — Resolved: 16 unit tests added (`a4f539a75`)
2. **Return value silently discarded at all call sites** — Resolved: all 13 CLI call sites now check return and print warnings (`a4f539a75`)
3. **First push failure swallowed without logging** — Resolved: `logger.debug` added (`a4f539a75`)
4. **R1. Stale docstring** — Resolved inline (`a95ce9f70`)

---

## Round 2

### Critical

_None remaining._

### Important

_None remaining._

### Resolved During Review (Round 2)

#### R4. Failing test: `test_no_session_id_raises_value_error`

**Location:** `tests/unit/test_todo_from_main.py:254-267`

The test did not mock `_collect_session_touched_files`, causing it to hit real infrastructure
(database query via `_create_sync_engine`). In any environment with a `teleclaude_session_id`
marker file, the test crashes with `OperationalError: no such table: sessions`.

Additionally, the test mocked `TELECLAUDE_SESSION_ID` env var, which is not read by the code
path (`_read_caller_session_id` reads from `$TMPDIR/teleclaude_session_id` file). The regex
match pattern was also case-mismatched.

**Fix:** Replaced with proper `_COLLECT` mock that raises `ValueError`, matching the actual
error propagation path. Test now passes in all environments.

#### R5. CLI surface.py still advertised removed `--paths` flag

**Location:** `teleclaude/cli/telec/surface.py:534-548`

The `from-main` command definition still listed `--paths` as a flag with usage examples and
notes, but the handler removed this parameter. CLI help text (which feeds agent system prompts)
would advertise a non-existent flag, causing confusing errors.

**Fix:** Removed `--paths` flag and updated notes to describe automatic session-transcript
scoping.

#### R6. Defensive `getattr` on declared model field

**Location:** `teleclaude/todo_scaffold.py:554`

Used `getattr(row, "native_log_file", None)` on a `db_models.Session` model where
`native_log_file` is a declared column (`str | None = None`). Direct attribute access
is correct and clearer.

**Fix:** Changed to `row.native_log_file`.

### Suggestions

#### 4. Repeated lazy-import pattern across 13 call sites (carried from Round 1)

Each handler has the identical import+call block. A module-level import or thin wrapper
would reduce noise. Not blocking.

#### 5. Double `Repo` instantiation in `_ensure_todo_on_remote_main` (carried from Round 1)

Creates `Repo(cwd)` for fetch/ls-tree checks, then `commit_bookkeeping_to_main` creates
another. Minor inefficiency.

## Lane Summaries (Round 2)

### Code

No bugs found. Round 1 findings #1-#3 verified as properly resolved. The `commit_bookkeeping_to_main`
extraction is clean. `_collect_session_touched_files` correctly reuses checkpoint infrastructure.
Fail-fast behavior correct throughout.

### Paradigm

Consistent with codebase patterns. Lazy imports follow convention. DRY refactor of
`_ensure_todo_on_remote_main` is well-executed. Session-transcript scoping reuses existing
infrastructure.

### Principles

No violations. Best-effort push justified. `--no-verify` documented with concrete rationale.
No unjustified fallbacks — all early returns are correct no-ops.

### Security

Clean. No secrets, tokens, or credentials. No injection vectors. Env bypass correctly scoped
in try/finally. `--no-verify` justified for bookkeeping artifacts.

### Tests

16 unit tests for `commit_bookkeeping_to_main` cover: early returns with zero side effects,
full command sequence, commit message structure, push recovery (rebase, abort, swallowed abort),
env bypass ordering, and finally-block restoration on all failure paths. Coverage is thorough.
Existing `from-main` tests properly updated with `_COLLECT` mocks. Failing test (R4) fixed.

### Errors (silent failures)

All error paths properly handled. `commit_bookkeeping_to_main`: `warning` on commit failure,
`debug` on first push failure, `warning` on push deferral. CLI handlers print user-visible
warnings for actionable failures. No silent swallowing.

### Comments

All comments accurate. Docstrings match behavior. `--no-verify` rationale comment is correct.
Stale docstring from R1 was previously fixed.

### Logging

Appropriate levels throughout. `info` on success, `warning` on failure, `debug` for
diagnostic details. No gaps at key boundaries.

### Why No Issues (Zero-finding justification)

1. **Paradigm-fit:** Verified lazy imports, return-value pattern, env bypass pattern, DRY
   extraction all match existing codebase conventions.
2. **Requirements:** Delivery matches the ad-hoc requirement: `commit_bookkeeping_to_main`
   extracted and called from all CLI handlers that write bookkeeping on main.
3. **Copy-paste duplication:** The 13 call-site blocks are identical in structure but differ
   in paths and subjects — this is not extractable without over-abstraction (Suggestion #4).
4. **Security reviewed:** All findings in this section are from direct inspection of the diff.

## Verdict: APPROVE

0 Critical findings, 0 Important findings. 3 findings auto-remediated during review (R4-R6).
2 Suggestions carried from Round 1 (non-blocking).
