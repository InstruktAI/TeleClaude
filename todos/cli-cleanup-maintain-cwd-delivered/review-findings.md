# Review Findings: cli-cleanup-maintain-cwd-delivered

## Critical

### C1: Orchestrator instruction templates still reference removed CLI flags

**Files:** `teleclaude/core/next_machine/core.py`

The `POST_COMPLETION` instruction dict (lines 150, 153, 167, 170, 184, 190, 194, 211, 224) and the build-gate failure output (line 510) still contain `--cwd <project-root>` in commands like:

```
telec todo mark-phase {args} --phase build --status complete --cwd <project-root>
telec todo verify-artifacts {args} --phase build --cwd <project-root>
```

The `pre_dispatch` f-string (line 3061) also references `--cwd <project-root>`:

```python
pre_dispatch = f"telec todo mark-phase {resolved_slug} --phase build --status started --cwd <project-root>"
```

Line 269 references `--project-root` in the finalize instructions:

```
telec roadmap deliver {args} --commit "$MERGE_COMMIT" --project-root "$MAIN_REPO"
```

**Impact:** These are instructions the orchestrator agent executes as CLI commands. With the flags removed:

- `verify-artifacts` rejects `--cwd` with "Unknown option" and exits 1 (hard crash)
- `mark-phase` and `set-deps` silently skip `--cwd` but parse its _value_ as a positional arg, **overwriting the slug** with the path
- `roadmap deliver` rejects `--project-root` with "Unknown option" and exits 1 (hard crash)

**Fix:** Remove `--cwd <project-root>` from all instruction template strings in `POST_COMPLETION`, the gate-failure output, and the `pre_dispatch` string. Remove `--project-root "$MAIN_REPO"` from the finalize instructions. The CLI handlers already default to `os.getcwd()` / `Path.cwd()`.

### C2: Demo uses nonexistent `--delivered` flag

**File:** `demos/cli-cleanup-maintain-cwd-delivered/demo.md:24`

Step 4 validation uses `telec roadmap list --delivered` but the CLI only accepts `--include-delivered` (or `-d`). The handler at `telec.py:2195` checks for `("--include-delivered", "-d")`. Passing `--delivered` hits the unknown-option guard and exits 1.

**Fix:** Change `--delivered` to `--include-delivered` (or `-d`) in the demo script.

## Important

### I1: `project_setup/sync.py` generates service files with removed `--project-root` flag

**File:** `teleclaude/project_setup/sync.py:53,136`

This file generates launchd plist and systemd service commands that still pass `--project-root`:

- Line 53: `telec watch --project-root {project_root}` — `_handle_watch` now ignores all args, so the watch runs against `cwd` instead of the specified project path (silent behavioral regression)
- Line 136: `telec sync --warn-only --project-root {project_root}` — `_handle_sync` rejects unknown flags, so newly generated sync services would crash on startup

Not in the diff, but this file was not identified in the requirements as a subprocess caller despite shelling out to `telec` commands with the removed flag.

**Fix:** Remove `--project-root {project_root}` from both command strings. For the watch case, the launchd/systemd service should set `WorkingDirectory` to the project root instead.

### I2: `assemble_roadmap` orphan-directory scan does not filter for `delivered_only`

**File:** `teleclaude/core/roadmap.py` — step 3 (orphan scan, ~line 243)

When `delivered_only=True`, steps 1 and 2 are correctly skipped. But step 3 scans orphan directories in `todos/` and adds any untracked non-icebox directory as a regular item. There is no `delivered_only` guard — unlike the existing `icebox_only` guard at the same location:

```python
# Existing guard for icebox_only:
if icebox_only and not is_icebox:
    continue
# Missing: equivalent guard for delivered_only
```

**Impact:** `telec roadmap list --delivered-only` may show orphan todo directories alongside delivered items, violating the "only delivered items" contract.

**Fix:** Add a `delivered_only` guard analogous to the icebox one, filtering orphan entries against the delivered slugs set.

### I3: Duplicate test `test_bugs_list_uses_worktree_state_for_status`

**Files:** `tests/unit/test_telec_cli.py:315` and `tests/unit/test_bugs_list_status_parity.py:12`

Identical test body in both files. Runs twice in CI for no benefit.

## Suggestions

### S1: Demo references removed internal constant `_PROJECT_ROOT_LONG`

**File:** `demos/cli-cleanup-maintain-cwd-delivered/demo.md:43`

The guided presentation says "matching the behavior of `telec todo work` and other commands that use `_PROJECT_ROOT_LONG`." This constant was removed in this PR.

### S2: No test coverage for `--include-delivered` / `--delivered-only` flags

No unit or integration test verifies the new delivered flags on `telec roadmap list`. The existing test pattern (e.g., `test_docs_phase1_parses_flags_and_calls_selector`) could be mirrored for delivered flags.

---

## Paradigm-Fit Assessment

1. **Data flow:** The delivered loading correctly reuses the existing `load_delivered` function from `core.py`. No bypass or inline hack. Pass.
2. **Component reuse:** The `assemble_roadmap` extension mirrors the icebox pattern (step 2 → step 2b). The CLI flag pattern mirrors `--include-icebox`/`--icebox-only`. The `TodoInfo.delivered_at` field follows the existing dataclass convention. Pass.
3. **Pattern consistency:** The flag removal pattern is consistent across all handlers. The `--cwd` removal in `tool_commands.py` correctly sets `os.getcwd()` unconditionally. The `handle_todo_work` backward-compat shim was preserved (pre-existing). Pass.

---

## Verdict: REQUEST CHANGES

Critical findings C1 and C2 must be addressed. C1 will break orchestrator agent workflows at runtime. C2 will fail demo validation.
