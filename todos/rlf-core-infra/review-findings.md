# Review Findings: rlf-core-infra

**Reviewer:** Claude (Opus 4.6)
**Round:** 2
**Date:** 2026-03-13

## Summary

Structural decomposition of three monolithic infrastructure modules into focused packages.
The core deliverable is clean, correct, and well-executed. All submodules are within the
800-line ceiling, public APIs are preserved via `__init__.py` re-exports, mixin TYPE_CHECKING
stubs are accurate, dependency graphs are acyclic, and all 172 unit tests pass. No behavioral
changes detected in the decomposed code.

Two issues were auto-remediated during review (see Resolved During Review section).

## Critical

None.

## Important

None (all Important findings were resolved during review).

## Suggestions

### S1: `_output.py` not listed in implementation plan

**Location:** `teleclaude/core/adapter_client/_output.py` (446 lines)
**Plan reference:** Implementation plan Phase 3 lists `_channels.py`, `_remote.py`, `_client.py`
but not `_output.py` or `_OutputMixin`.

The plan describes `_client.py` as containing "lifecycle, routing, messaging" but the builder
further decomposed messaging/output into `_output.py`. This is better granularity that serves
the line-limit goals, but the plan should have been updated to reflect the actual delivery.

No action required — the decomposition is correct. Plan-to-delivery traceability note only.

### S2: Guardrail adjustments beyond decomposition scope

**Location:** `tools/lint/guardrails.py`
**Detail:** Several guardrail changes go beyond what the structural decomposition requires:

- `max_allowed` for loose dict violations: 0 → 78 (recognizing pre-existing violations)
- Removed redundant second `_fail()` call that always triggered on any loose dicts
- `RUFF_MAX_PER_FILE_IGNORE_ENTRIES`: 43 → 52
- Introduced `MODULE_SIZE_ALLOWLIST` dict for known-large files pending decomposition
- `ws_mixin.py` C901 addition in `pyproject.toml` (unrelated to decomposition)

These are pragmatic corrections — the old loose-dict guardrail was effectively broken
(always failing), and the size allowlist documents the decomposition roadmap. The
ratchet-down comments indicate intent to reduce. Acceptable as-is but noted as scope
expansion.

### S3: Out-of-scope changes included in the diff

**Detail:** Several changes are unrelated to structural decomposition:
- Mermaid diagram `\n` → `<br/>` reformatting across 4 doc files (rendering fix)
- Agent command refactoring in `next-bugs-fix.md`, `next-build-specs.md`,
  `next-build.md`, `next-review-specs.md` (section inlining)
- Formatting-only changes in adapter/API files (linter auto-format)
- `prepare_steps` patch path updates in commit `c9ae097ba` (different decomposition scope)

These came from upstream main merges and worktree sync. Non-blocking but inflates the diff.

### S4: Unused constants in `_client.py`

**Location:** `teleclaude/core/adapter_client/_client.py:30-31`
**Detail:** `_OUTPUT_SUMMARY_MIN_INTERVAL_S` and `_OUTPUT_SUMMARY_IDLE_THRESHOLD_S` are
defined but unused anywhere in the codebase. Pre-existing from the original monolithic file,
not introduced by this decomposition. Could be cleaned up in a future pass.

### S5: Import style inconsistency in `__init__.py` files

**Detail:** `agent_coordinator/__init__.py` uses absolute imports while
`adapter_client/__init__.py` uses relative imports. Both work correctly.
Stylistic inconsistency only — no functional impact.

### S6: Requirements.md is an empty scaffold

**Location:** `todos/rlf-core-infra/requirements.md`
**Detail:** The requirements file contains only the template structure with no filled-in
content. For a pure structural refactoring, the implementation plan serves as the de facto
specification. Weakens formal traceability but acceptable for this task type.

### S7: tmux_bridge `__all__` expanded from 20 to 35 symbols

**Location:** `teleclaude/core/tmux_bridge/__init__.py`
**Detail:** 15 previously non-exported symbols (subprocess utilities, pane query functions)
are now explicitly in `__all__`. These were always accessible via attribute access on the
module; the expansion makes the contract explicit. This is positive — no symbols were lost.

### S8: Test patch paths coupled to internal submodule structure

**Location:** `tests/unit/core/test_agent_coordinator.py`
**Detail:** All `patch()` targets now reference internal submodule paths
(`_coordinator.db`, `_coordinator.is_threaded_output_enabled`, `_fanout.db`).
This is technically correct (patches must target where the name is looked up) but
couples tests to internal package structure. An inherent trade-off of the decomposition
— no alternative exists without re-exporting `db` through `__init__.py`.

## Resolved During Review

### R1: Test coverage gap — `_extract_user_input_for_codex` method mocked out

**Original severity:** Important
**Location:** `tests/unit/core/test_agent_coordinator.py:159-229` (3 tests)

**Issue:** Three `handle_agent_stop` tests added `patch.object(coord,
"_extract_user_input_for_codex", new_callable=AsyncMock, return_value=None)` which
suppressed a code path that was previously exercised through the mocked `db`. Root cause:
after decomposition, `_extract_user_input_for_codex` lives in `_fanout.py` which imports
`db` from its own namespace — the test's `_coordinator.db` patch didn't cover it.

**Fix:** Replaced the method mock with `patch("teleclaude.core.agent_coordinator._fanout.db",
db_mock)` so the real method executes through the mocked db (returning None for non-Codex
sessions via the `active_agent != "codex"` check). Restores the original test coverage.

### R2: Lazy import of `AgentOutputPayload` in `_coordinator.py`

**Original severity:** Suggestion
**Location:** `teleclaude/core/agent_coordinator/_coordinator.py:684`

**Issue:** `AgentOutputPayload` was imported lazily inside `handle_tool_use` instead of at
module level, inconsistent with `_incremental.py` which imports it eagerly.

**Fix:** Moved the import to the top-level import block (line 21) and removed the inline
import. Consistent with the original monolith and with `_incremental.py`.

**Verification:** All 172 unit tests pass after both remediations.

## Verification Evidence

### Paradigm-fit
- Mixin pattern follows the existing `daemon_event_platform.py` precedent for
  `TYPE_CHECKING` stubs
- `__init__.py` re-export pattern is standard Python packaging
- No new patterns introduced
- Dependency graphs verified acyclic for all 3 packages:
  - tmux_bridge: `_subprocess` ← `_pane` ← `_session` ← `_keys`
  - agent_coordinator: `_helpers` ← `{_fanout, _incremental}` ← `_coordinator`
  - adapter_client: `{_channels, _output, _remote}` ← `_client`

### Completeness
- All 12 implementation plan tasks checked `[x]`
- All 3 packages import correctly (verified via Python import)
- All submodules within 800-line ceiling (max: 727 lines in `_coordinator.py`)
- All 172 unit tests pass (full suite verified)
- Demo blocks all execute successfully

### Silent failure audit
- No import resolution gaps: all external consumers use package-level imports
- No `__all__` gaps: every externally-used symbol is re-exported
- No MRO issues: linear mixin chains, no diamond inheritance
- No broad exception handlers swallowing import errors
- Module-level side effects (e.g., `_SHELL_NAME`) preserved at original import time
- Original monolith `.py` files properly deleted — no shadowing

### Security
- No credentials, tokens, or secrets in the diff
- No new user input handling or shell command construction
- No injection vectors introduced
- Purely structural change — security posture unchanged

### Why No Important/Critical Findings

1. **Paradigm-fit verified:** mixin pattern matches `daemon_event_platform.py` precedent;
   `__init__.py` re-exports follow standard packaging
2. **All requirements met:** 3 monoliths decomposed into packages with backward-compatible APIs;
   all external consumers import from package level without changes
3. **Copy-paste duplication checked:** no duplicated logic across submodules; shared imports
   are the only repetition (necessary for separate modules)
4. **Security reviewed:** no secrets, injection, or auth changes
5. **Re-export completeness verified:** every `__init__.py` re-export checked against external
   consumers; `tmux_bridge` expansion from 20 to 35 symbols covers all externally-used functions
6. **TYPE_CHECKING stubs verified:** all mixin stubs match actual host class implementations
7. **MRO verified:** linear chains, no diamond inheritance
8. **Test coverage maintained:** auto-remediated the `_fanout.db` patch gap to preserve
   coverage of the codex extraction code path

## Deferrals Assessment

The deferral for pre-existing mypy/pyright failures is justified:
- 5844 mypy errors across 272 files on main before this branch
- 73 pyright errors across 24 files, 18 from main merge
- The decomposition did not increase the error baseline
- A dedicated typing task is the appropriate resolution

## Verdict

**APPROVE**

The structural decomposition is clean, correct, and backward-compatible. All submodules
are within size limits, public APIs are preserved, mixin patterns are properly typed,
dependency graphs are acyclic, and all 172 tests pass. Two issues were auto-remediated
during review (test coverage gap and lazy import). The remaining suggestions are
documentation, scope, and style notes — none affect correctness or safety.
