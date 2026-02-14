# Review Findings: release-manifests

## Round 1

### Critical

1. **index.yaml worktree path corruption** — `docs/project/index.yaml:1-2` and `docs/third-party/index.yaml:1`
   Both index files had their paths rewritten from `~/Workspace/InstruktAI/TeleClaude` to `~/Workspace/InstruktAI/TeleClaude/trees/release-manifests`. When merged to main, these would point to a non-existent worktree directory, breaking all documentation indexing and `telec sync`. These changes must be reverted before merge.

### Important

2. **Build gate violation: uncommitted state.json** — `todos/release-manifests/state.json`
   The quality checklist marks "Code committed" and "Working tree clean" as checked, but `state.json` has uncommitted changes (`build: pending` in committed version vs `build: complete` in working tree). The build gates are not truthfully satisfied.

3. **Out-of-scope change** — `scripts/diagrams/extract_runtime_matrix.py:89`
   The fix to narrow `transcript_discovery` detection is unrelated to the release-manifests scope. While the fix itself is correct (removing a redundant `"transcript_path=" in content` condition that was already handled by the `transcript_path` feature above), it belongs on its own branch/commit rather than bundled with manifest work.

### Suggestions

4. **Hardcoded standard events in test** — `tests/integration/test_contracts.py:61-70`
   `test_event_vocabulary_contract` hardcodes `known_standard` events instead of deriving them from a code-level enum or constant. If a new standard event is added to the codebase without updating this set, the contract test won't catch the drift. Consider extracting standard events from a code-level source similar to how `AgentHookEvents.RECEIVER_HANDLED` is used for hook events.

5. **Shallow config contract test** — `tests/integration/test_contracts.py:78-85`
   `test_config_contract` only checks top-level config key names without validating sub-schema structure. This limits its ability to detect breaking changes like removing a nested key (e.g., `redis.host`) from the config surface.

## Verdict

**REQUEST CHANGES**

Blocking issues: Critical #1 (index.yaml corruption) and Important #2 (build gate violation) must be resolved before approval.

## Fixes Applied

- Issue #1 (Critical): Restored stable repository-root paths in `docs/project/index.yaml` and `docs/third-party/index.yaml` to prevent worktree-only path leakage after merge.
  - Commit: `e62fb890`
- Issue #2 (Important): Committed current todo state so build/review gate tracking is no longer uncommitted local state.
  - Commit: `511d95c4`
- Issue #3 (Important): Attempted to remove out-of-scope change by restoring previous detection logic in `scripts/diagrams/extract_runtime_matrix.py`, but this caused a regression in `tests/unit/test_diagram_extractors.py::test_extract_runtime_matrix_regression` (Codex incorrectly regained `transcript_discovery`). Kept tested behavior and documented blocker for follow-up branch handling.
  - Commit: none (reverted during verification)
