# Review Findings: cli-cleanup-maintain-cwd-delivered

## Round 2

### Critical

#### C1-R2: C1 fix corrupted POST_COMPLETION instruction templates (collapsed newlines + 2 missed occurrences)

**File:** `teleclaude/core/next_machine/core.py`

The round 1 C1 fix removed `--cwd <project-root>` from instruction template strings but collapsed the trailing newlines, merging adjacent lines. It also missed 2 occurrences entirely.

**Collapsed newlines** — each line below shows the corrupted merged content:

| Line | Corrupted content                                                | Impact                                                          |
| ---- | ---------------------------------------------------------------- | --------------------------------------------------------------- |
| 150  | `verify-artifacts {args} --phase build   - If FAIL: send the...` | CLI receives `- If FAIL:` as extra args → unknown option exit 1 |
| 152  | `--status complete4. Call {next_call}`                           | Status value becomes `complete4.` → invalid status              |
| 165  | Same as 150 (next-bugs-fix template)                             | Same crash                                                      |
| 167  | Same as 152 (next-bugs-fix template)                             | Same invalid status                                             |
| 180  | `verify-artifacts {args} --phase review   - If FAIL:`            | Same crash                                                      |
| 185  | `--status approved   c. Call {next_call}`                        | Status becomes `approved   c.` → invalid                        |
| 188  | `--status changes_requested   c. Dispatch fixer:`                | Status becomes `changes_requested   c.` → invalid               |
| 217  | `--status pending4. Call {next_call}`                            | Status becomes `pending4.` → invalid                            |
| 502  | `--status complete   b. Call {next_call}`                        | Status becomes `complete   b.` → invalid                        |

**Missed occurrences** — `--cwd <project-root>` was NOT removed from:

- Line 204: `telec todo mark-phase {args} --phase review --status approved --cwd <project-root>,`
- Line 3052: `pre_dispatch = f"telec todo mark-phase {resolved_slug} --phase build --status started --cwd <project-root>"`

**Fix:** Restore proper newlines at each location where the removal collapsed them. Remove the 2 remaining `--cwd <project-root>` occurrences. Each `telec` command in the instruction template must be on its own line, with following prose (step numbers, conditionals) on separate lines.

### Suggestions

#### S1-R2: Demo guided presentation has stale references (carried from R1)

**File:** `demos/cli-cleanup-maintain-cwd-delivered/demo.md`

- Line 43: References removed `_PROJECT_ROOT_LONG` constant.
- Line 49: Uses `telec roadmap list --delivered` instead of `--include-delivered`. (Validation step 4 at line 24 was correctly fixed; this is the guided presentation copy.)

---

## Round 1 (for reference)

### Fixes Applied

| Issue | Fix                                                                                                                            | Commit   |
| ----- | ------------------------------------------------------------------------------------------------------------------------------ | -------- |
| C1    | Partial — removed most `--cwd <project-root>` from instruction templates (introduced collapsed newlines, missed 2 occurrences) | 77ae5ace |
| C2    | Changed `--delivered` to `--include-delivered` in demo validation step 4                                                       | 77ae5ace |
| I1    | Removed `--project-root {project_root}` from launchd/systemd in `sync.py`, added `WorkingDirectory`                            | 77ae5ace |
| I2    | Added `if delivered_only: continue` guard to orphan scan in `assemble_roadmap`                                                 | 77ae5ace |
| I3    | Deleted duplicate `tests/unit/test_bugs_list_status_parity.py`                                                                 | 77ae5ace |

---

## Paradigm-Fit Assessment

1. **Data flow:** The delivered loading correctly reuses the existing `load_delivered` function from `core.py`. No bypass or inline hack. Pass.
2. **Component reuse:** The `assemble_roadmap` extension mirrors the icebox pattern (step 2 → step 2b). The CLI flag pattern mirrors `--include-icebox`/`--icebox-only`. The `TodoInfo.delivered_at` field follows the existing dataclass convention. Pass.
3. **Pattern consistency:** The flag removal pattern is consistent across all CLI handlers. The `--cwd` removal in `tool_commands.py` correctly sets `os.getcwd()` unconditionally. The `handle_todo_work` backward-compat shim was preserved (pre-existing). Pass.

---

## Verdict: REQUEST CHANGES

C1-R2 is critical — the POST_COMPLETION instruction templates that the orchestrator executes are corrupted with merged lines and 2 remaining `--cwd <project-root>` references. Every `telec todo mark-phase` and `telec todo verify-artifacts` command in those templates will either crash or receive garbage arguments.
