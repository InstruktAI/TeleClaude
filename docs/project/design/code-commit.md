---
id: 'project/design/code-commit'
type: 'design'
domain: 'software-development'
scope: 'project'
description: 'Design of telec code commit — the canonical agent commit command with session scoping, quality gates, and multi-agent protection.'
---

# Code Commit — Design

## Purpose

`telec code commit` is the canonical commit interface for agent sessions. It
resolves session-scoped files, stages them, runs formatting and linting, then
invokes `git commit`. The git wrapper redirects raw `git commit` to this command.
The generated pre-commit hook remains the owner of formatter restaging and the
single retry when hooks modify staged files.

The driving constraint: git ignores index changes made inside pre-commit hooks
when the commit starts with an empty index. `telec code commit` solves that by
staging session-scoped files before `git commit`, while the pre-commit hook
handles post-format restaging so plain `git commit` and wrapper-driven commits
share the same mutation recovery path.

## Inputs/Outputs

**Flag:** `-m <message>` — commit message (first-class, no `--` separator needed).

All other arguments pass through to `git commit`.

**Outputs:** committed changeset, or failure with actionable diagnostics.

## Invariants

1. **Lock serialization.** `main_branch_lock()` (flock) serializes the entire
   stage-format-lint-commit cycle. No two agents can commit concurrently.
   The lock auto-releases on process exit or crash.

2. **Foreign staged file detection.** Before staging, check if files are already
   staged that are outside the session scope. If found, exit with code 2
   (retryable) — another agent may be mid-commit with a failed pre-commit hook.
   The agent's heartbeat retries after conditions clear.

3. **Session scoping.** `tools/session_scope.py --mode lint` determines which
   files belong to the current session. In worktrees, the fallback is
   `git status --porcelain`. Outside agent sessions, scoping returns empty
   and whatever is already staged proceeds.

4. **Path A/B/C on main.** Non-integrator commits on main are classified:
   - **Path A:** all staged files non-functional + message contains `[skip ci]` → autonomous
   - **Path B/C:** functional files → human gate, exit with guidance

5. **Orchestrator restriction.** Orchestrators cannot commit on any branch.

6. **Format then lint.** Formatting runs first. The pre-commit hook restages
   formatter-modified files and retries once if needed, so raw `git commit`
   and `telec code commit` behave the same.

7. **Wrapper redirect.** The git wrapper blocks `git commit` and directs agents
   to `telec code commit`. The wrapper retains all other safety blocks
   (stash, checkout, restore, clean, reset, push on main).

8. **Real git bypass.** The final `git commit` call uses the real git binary
   (bypassing the wrapper) since the wrapper would redirect back.

## Primary flows

### Agent commit (worktree)

```
telec code commit -m "feat(scope): subject"
  → lock acquired
  → no foreign staged files
  → session_scope resolves touched files
  → git add -- <files>
  → FormatRunner.run(files=staged)
  → LintRunner.run(files=staged)
  → real git commit -m "feat(scope): subject"
  → lock released
```

### Agent commit on main (Path A — non-functional)

```
telec code commit -m "chore(docs): update snippets [skip ci]"
  → lock acquired
  → session scope + stage
  → Path A: no functional files + [skip ci] → proceed
  → format + lint + commit
```

### Integration commit

The integrator uses `telec code commit` with files already staged from the
squash merge. Session scoping finds no additional files. The integrator role
bypasses Path A/B/C classification.

## Failure modes

**Lock contention.** Another agent holds the lock. `flock(LOCK_EX)` blocks
until released. No timeout — the agent waits.

**Foreign staged files.** Exit code 2. Agent retries on heartbeat. By then the
other agent's commit may have completed (clearing the index) or the human
may have cleaned up.

**Lint failure.** `LintRunner.run()` raises `SystemExit`. Files remain staged
for the agent to fix and retry.

**Path B/C gate.** Functional files on main without human approval. Exit with
guidance. The human intervenes or routes through the review pipeline.

## See Also

- docs/global/software-development/design/session-file-scoping.md
- docs/global/software-development/policy/version-control-safety.md
