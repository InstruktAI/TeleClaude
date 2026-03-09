# todo-phase-status-display-2 — Input

## Worktree Base Sanity — Friction Report

### What happened
During the build phase for todo-phase-status-display, the builder completed all 9 implementation tasks in ~20 minutes with 8 commits, tests passing in-worktree, lint clean. BUILD COMPLETE reported.

The orchestrator (me) then made a sequencing error: ended the builder session BEFORE running `telec todo work` (which executes build gates). Gates failed with 40 test failures. All 40 failures were pre-existing in the worktree — they pass on main (3334 passed, 0 failed on main).

Root cause: the worktree was branched from grounding sha `d06c63c4e` which predates test fixes now on main. The `_merge_origin_main_into_worktree()` mechanism (core.py:1253) either didn't fire or origin/main was behind local main.

Had to re-dispatch a second builder session (e3bced95) just to rebase the worktree onto main and manually apply test fixes one file at a time. This burned ~15+ minutes of pure waste — the feature code was done.

### Code findings (verified, not assumed)
1. **Worktree creation** (`core.py:2674`): Branches from local HEAD, NO fetch/pull before creation.
2. **Origin/main merge** (`core.py:1253`): Fetches and merges origin/main into worktree DURING build dispatch (not creation). Fetch failure is silently non-fatal — logs warning, continues.
3. **No green-main gate**: `telec todo work` does NOT verify tests pass on the base commit before dispatching work.

### Mo's feedback (verbatim sentiment)
- "Something is seriously wrong" with the process taking this long
- "We should not be entering work without having green tests on main in the first place"
- "Why is main dirty? Why are todos created from dirty main?"
- "I want main at all times to be green"
- "If local main is dirty, pull from something sane — from the remote. The integrator is always pushing to main and what is on the remote should be more sane than the local branch."

### Proposed fixes (discussed with Mo, not yet implemented)
1. **Gate main before work starts**: `telec todo work` should refuse to dispatch if `make test` fails on the base commit. Broken main = no new work.
2. **Base worktrees on `origin/main`, not local HEAD**: Change `_create_or_attach_worktree()` to `git worktree add <path> -b <slug> origin/main`. The integrator pushes verified green state to origin — that's the last known-good artifact.
3. **Make origin/main fetch failure loud**: The silent non-fatal fetch in `_merge_origin_main_into_worktree()` should be a blocking error. A builder starting on a stale base is the exact failure mode we hit.
4. **Uncommitted test changes on main are the smell**: If test files are modified but uncommitted on main, that state leaks into worktree creation. Basing on origin/main eliminates this.

### Orchestrator error to learn from
I ended the builder session before running the state machine's gate check. The correct sequence per the orchestration procedure is: run `telec todo work` (which runs gates) → handle gate result → THEN end session. Ending first meant I had to cold-start a new builder session with full context reload just to do a rebase.

### Current status
- Builder session e3bced95 is still running, manually applying test fixes from main into the worktree
- All feature implementation code is done and committed (8 commits from first builder)
- Once tests pass in worktree, gates should clear and we proceed to review
