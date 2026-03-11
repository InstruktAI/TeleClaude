# Review Findings: telec-init-enrichment

## Round 1 — Resolved During Review

The following issues were found and fixed inline during the round 1 review pass:

1. **Worktree path contamination in index.yaml files** — `docs/project/index.yaml`,
   `docs/third-party/index.yaml`, and `docs/global/index.yaml` contained worktree-specific
   paths (`trees/telec-init-enrichment/`) or tilde-normalized paths that differ from main.
   Reverted to canonical project paths.

2. **Non-interactive enrichment auto-launch** — `_offer_enrichment()` used
   `_prompt_yes_no()` with `default=True`, causing enrichment to launch automatically
   when stdin is not a TTY (CI, agent contexts). Added early return for non-interactive
   contexts.

3. **Config destruction on YAML parse failure** — `_prompt_release_channel()` fell back
   to `raw = {}` on any exception, then wrote that back to `teleclaude.yml`, potentially
   destroying all config. Changed to log warning and return without writing.

4. **No logging in enrichment.py** — 275-line I/O module with zero diagnostic output.
   Added `logging` import and `logger` instance.

5. **Silent exception handlers** — All `except Exception` blocks in `enrichment.py` and
   `init_flow.py` now bind the exception variable and log at appropriate levels. Also
   changed `frontmatter.load(file_path)` to `frontmatter.loads(existing_content)` in
   `refresh_snippet()` to eliminate redundant disk read.

6. **`snippet_id_to_path` crash on malformed input** — Public function raised opaque
   `IndexError` on input with fewer than 3 slash-separated parts. Added validation guard
   with descriptive `ValueError`.

7. **Dead filter in `read_existing_snippets`** — Removed `"index.yaml"` from the skip
   list since the `rglob("*.md")` glob already excludes `.yaml` files.

8. **`_launch_enrichment` error handling** — Widened `FileNotFoundError` to `OSError`
   (catches `PermissionError` too), added `capture_output=True` for diagnostic stderr,
   added `logger.warning()` calls on all failure paths.

9. **Pyright type error** — Fixed `compare_meta["generated_at"] = existing_ts` to check
   `isinstance(existing_ts, str)` instead of truthy, satisfying the TypedDict type.

## Round 1 Findings (now resolved)

### C1: No test coverage for new production code

**Status:** Overridden — test suite removed from main by user decision. Not a finding.

### C2: Demo assumes synchronous enrichment but session launches asynchronously

**Status:** Fixed in `2a89cc71f`. Initial enrichment wait block added. Re-init wait
block had a residual issue (polled for condition already true) — auto-remediated in
round 2 review (see below).

### I1–I5: All addressed in `2a89cc71f`

| Finding | Fix | Verified |
|---------|-----|----------|
| I1 | `_prompt_release_channel` uses `ruamel.yaml` comment-preserving write; only `deployment` section mutated | Correct — `ruamel.yaml` already a project dependency. Graceful fallback to plain dict on parse failure. |
| I2 | `write_snippet` delegates to `_render_snippet`; duplicate frontmatter construction removed | Correct — single source of truth for frontmatter at `_render_snippet:225`. |
| I3 | `refresh_snippet` return type narrowed to `RefreshResult = Literal["created", "updated", "unchanged"]` | Correct — type alias at line 23, return annotation at line 178, all three return sites match. |
| I4 | `read_metadata` validates all five required keys before casting to `AnalysisMetadata` | Correct — `_REQUIRED_META_KEYS` frozenset matches `AnalysisMetadata` TypedDict keys exactly. |
| I5 | `write_snippet` docstring corrected to match `SnippetMetadata(total=False)` contract | Correct — class docstring (line 27) and method param doc (line 106) both accurately describe optional fields. |

## Round 2 — Resolved During Review

1. **Demo re-init wait block polled a pre-existing condition** — The re-init validation
   block polled `grep -q "Human addition"` after appending that text and before enrichment
   could run. The condition was already true, so the poll succeeded immediately without
   proving enrichment completed and preserved human edits. Fixed by recording the
   `last_analyzed_at` timestamp before re-init and polling until it changes, then
   verifying human edits survived.

## Critical

_(none)_

## Important

_(none)_

## Suggestions

### S1: `_prompt_release_channel` silently overwrites `pinned_minor` on channel switch

**Location:** `teleclaude/project_setup/init_flow.py:98`

When switching from stable to alpha/beta, `pinned_minor` is set to `""` and written
back. If the user switches back to stable later, they must re-enter their pinned
version. Consider only clearing `pinned_minor` when explicitly changing away from stable.

### S2: `SnippetMetadata.type` should use `Literal` for taxonomy types

The field accepts arbitrary `str` when only six values are valid. A typo like
`"polciy"` would silently produce an invalid snippet. This aligns with I3 —
the module should use tighter types throughout.

## Why No Issues

1. **Paradigm fit verified:** The enrichment module follows established project patterns —
   TypedDicts for typed dicts, `frontmatter` library for snippet I/O, `logging` for
   diagnostics, `ruamel.yaml` for comment-preserving YAML (same as `config_handlers.py`).
   Init flow integration follows the existing sequential-steps pattern with optional
   interactive prompts gated on `sys.stdin.isatty()`.

2. **Requirements verified against code:**
   - Enrichment prompting (first-init vs re-init): `_offer_enrichment` at init_flow.py:158
   - Async session launch: `_launch_enrichment` at init_flow.py:131
   - Snippet validation boundary: `validate_snippet_id` + path-escape check at enrichment.py:114–122
   - Human-edit merge: `merge_snippet` at enrichment.py:156 + `refresh_snippet` at enrichment.py:173
   - Metadata persistence: `write_metadata`/`read_metadata` at enrichment.py:242/265
   - Release channel enrollment: `_prompt_release_channel` at init_flow.py:56
   - Plumbing continuity: enrichment is appended after all existing steps at init_flow.py:208

3. **Copy-paste duplication checked:** I2 fix confirmed — `write_snippet` delegates to
   `_render_snippet`. No remaining duplicated frontmatter construction.

4. **Security reviewed:** Path-escape validation at enrichment.py:120–122 prevents writes
   outside `docs/project/`. No secrets in diff. No injection vectors (subprocess args are
   list-based). Error messages expose only file paths, not internal state.

## Round 3 — Post-Finalize Merge Verification

Scope: verify the `229c6dfc5` merge of `origin/main` into `telec-init-enrichment`
introduced no conflicts or regressions.

Commits since baseline (`c00fbf00a`):
- `30822e2da` — process deferrals, NOOP (no code changes)
- `3d12f9ff4` — fix(titling): freeze slash-command session titles (origin/main)
- `229c6dfc5` — merge commit

The only code change is `teleclaude/core/agent_coordinator.py` — the titling fix.
This file is entirely outside the init-enrichment scope. Merge is clean (no conflict
markers, no merge artifacts). The titling change is a backward-compatible signature
extension (`prompt_text: str = ""`) plus two early-return guards — no functional
interaction with any init-enrichment path.

No new Critical or Important findings.

## Verdict: APPROVE

All Critical and Important findings from round 1 are resolved. C1 overridden per user
decision (test suite removed). C2 and I1–I5 fixed in `2a89cc71f`, verified correct.
Round 2 auto-remediated one residual demo polling issue. Round 3 merge verified clean.
Two Suggestion findings remain (S1, S2) — non-blocking.
