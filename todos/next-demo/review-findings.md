# Review Findings: next-demo

**Review round:** 1
**Reviewer:** Claude (Opus 4.6)
**Date:** 2026-02-21
**Verdict:** REQUEST CHANGES

---

## Critical

### R1-F1: Index YAML paths rewritten to worktree-specific paths

**Files:** `docs/project/index.yaml:1-2`, `docs/third-party/index.yaml:1`

`telec sync` rewrote the `project_root` and `snippets_root` fields to point to the worktree (`~/Workspace/InstruktAI/TeleClaude/trees/next-demo`) instead of the canonical project root (`~/Workspace/InstruktAI/TeleClaude`). After merge to main, these paths will point to a non-existent directory, breaking doc snippet resolution for the entire project.

**On main:**

```yaml
project_root: ~/Workspace/InstruktAI/TeleClaude
snippets_root: ~/Workspace/InstruktAI/TeleClaude/docs/project
```

**On this branch:**

```yaml
project_root: ~/Workspace/InstruktAI/TeleClaude/trees/next-demo
snippets_root: ~/Workspace/InstruktAI/TeleClaude/trees/next-demo/docs/project
```

Same issue affects `docs/third-party/index.yaml`.

**Fix:** Revert the `project_root` and `snippets_root` paths in both files to their canonical values. Only the new `project/spec/demo-artifact` snippet entry should remain as a diff.

### R1-F2: Git metrics in next-demo command will produce empty results after finalize merge

**File:** `agents/commands/next-demo.md:43`

Step 3 says: `git log --oneline main..HEAD` to get commit count. However, the demo runs **after finalize has already merged** the slug branch into main. At that point:

- From the worktree: `main` now includes all slug commits (via merge), so `main..HEAD` is empty.
- From the main repo: `HEAD == main`, so `main..HEAD` is trivially empty.

The commit count, files changed, lines added/removed — all metrics sourced from `main..HEAD` — will be zero.

**Fix:** The command should use merge-base comparison: `git log $(git merge-base main~1 HEAD)..HEAD` from the worktree, or capture the pre-merge main position before finalize. Alternatively, use the slug branch name explicitly: `git log $(git merge-base main {slug})..{slug}` (but post-merge this also breaks since slug is now an ancestor of main). The cleanest fix is to have the command reference the merge commit: `git diff main~1..main --stat` from the main repo, which shows exactly what the merge introduced.

---

## Important

### R1-F3: Demo dispatch uses `subfolder=""` instead of worktree path

**File:** `teleclaude/core/next_machine/core.py:147`

The finalize POST_COMPLETION dispatches demo with `subfolder=""`, which means the demo agent starts at the main repo root. But the command's steps 2-3 assume the agent is in the worktree (reading `todos/{slug}/` artifacts, running `git log main..HEAD` where HEAD is the slug branch). Other worker commands (build, review, fix) all use `subfolder=f"trees/{resolved_slug}"`.

**Fix:** Change to `subfolder="trees/{args}"` so the demo agent runs from the worktree, or redesign the command's git references to work from the main repo root.

### R1-F4: Command artifact missing formal Recovery section

**File:** `agents/commands/next-demo.md:59-60`

Lines 59-60 contain recovery/fallback instructions as loose bullets after the Steps section:

```
- If todo artifacts are already cleaned up, reconstruct from git log and todos/delivered.md.
- Demo failure is non-blocking — log a warning and exit cleanly.
```

Other commands (`next-build`, `next-review`, `next-finalize`) use a dedicated `## Recovery` section for this. The pattern violation makes it easy for an executing agent to miss these instructions.

**Fix:** Move the two bullets into a `## Recovery` section after Outputs.

### R1-F5: Missing edge case tests for demo.sh error paths

**File:** `tests/unit/test_next_machine_demo.py`

Two error paths in the demo.sh script are untested:

1. **Missing pyproject.toml:** The script walks up to `/` looking for `pyproject.toml` and falls back to `CURRENT_VERSION="0.0.0"`. This fallback path is never exercised.
2. **Missing snapshot.json:** The script exits 1 with an error message when `snapshot.json` is absent. This error path is never exercised.

Both are real-world scenarios (stale demo folder, corrupted artifact) and should be tested.

---

## Suggestions

### R1-F6: Demo spec doesn't document pyproject.toml search behavior

**File:** `docs/project/spec/demo-artifact.md:54-55`

The spec says demo.sh "Reads the current project version from pyproject.toml" but doesn't specify what happens when `pyproject.toml` is not in the demo's directory. The test implementation walks up the directory tree. This search strategy should be documented in the spec.

### R1-F7: Required reads could include demo-artifact spec

**File:** `agents/commands/next-demo.md:12`

The command's Required reads only reference `lifecycle/demo.md`. Since the command must produce artifacts conforming to `project/spec/demo-artifact`, that spec should also be listed to ensure the agent loads the schema definition.

### R1-F8: Global index.yaml path normalization is unrelated to demo feature

**File:** `docs/global/index.yaml:1-2`

The change from `/Users/Morriz/.teleclaude` to `~/.teleclaude` is a path normalization improvement but is unrelated to the demo feature. It should be a separate commit to keep the demo branch focused.

---

## Build section validation

- [x] All implementation-plan task checkboxes are `[x]`
- [x] Build gates in quality-checklist.md are all checked
- [x] No deferrals.md exists (none to validate)
- [ ] Code committed — state.json has uncommitted changes (M todos/next-demo/state.json)

---

## Verdict: REQUEST CHANGES

Two critical findings require resolution before approval:

1. **R1-F1** — Index YAML worktree paths will break doc resolution after merge.
2. **R1-F2** — Git metrics commands produce empty results after finalize merge, yielding incorrect demo artifacts.

Important findings R1-F3 through R1-F5 should also be addressed.
