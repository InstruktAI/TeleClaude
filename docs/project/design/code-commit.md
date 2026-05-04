---
id: 'project/design/code-commit'
type: 'design'
domain: 'software-development'
scope: 'project'
description: 'Design of telec code commit — the canonical agent commit command with shared-branch protections, worktree-wide staging, and quality gates.'
---

# Code Commit — Design

## Purpose

`telec code commit` is the canonical commit interface for agent sessions. On
shared branches it resolves session-scoped files and protects against foreign
staged work. In worktrees it treats the entire dirty tree as task scope and
stages everything. It then runs formatting and linting before invoking
`git commit`. The git wrapper redirects raw `git commit` to this command. The
generated pre-commit hook remains the owner of formatter restaging and the
single retry when hooks modify staged files.

The driving constraint: git ignores index changes made inside pre-commit hooks
when the commit starts with an empty index. `telec code commit` solves that by
staging the intended scope before `git commit`, while the pre-commit hook
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

2. **Shared-branch protection.** On shared branches, before staging, check if
   files are already staged that are outside the session scope. If found, exit
   with code 2 (retryable) — another agent may be mid-commit with a failed
   pre-commit hook. The agent's heartbeat retries after conditions clear.

3. **Scope depends on workspace kind.** Shared branches use session scoping.
   Worktrees are task-scoped, so `telec code commit` stages all dirty files
   with `git add -A`.

4. **Path A/B/C on main.** Non-integrator commits on main are classified:
   - **Path A:** all staged files non-functional + message contains `[skip ci]` → autonomous
   - **Path B:** small functional change, human-approved → commit directly (`--approved`)
   - **Path C:** functional change + review → commit with `--approved`, then dispatch
     `telec sessions run --command /next-review-commits --args '<shas>'`

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
  → worktree detected
  → git add -A
  → FormatRunner.run(files=staged)
  → LintRunner.run(files=staged)
  → real git commit -m "feat(scope): subject"
  → lock released
```

### Agent commit on main (Path A — non-functional)

```
telec code commit -m "chore(docs): update snippets [skip ci]"
  → lock acquired
  → session scope + foreign-staged protection + stage
  → Path A: no functional files + [skip ci] → proceed
  → format + lint + commit
```

### Integration commit

The integrator uses `telec code commit` with files already staged from the
squash merge. The integrator role bypasses Path A/B/C classification.

## Failure modes

**Lock contention.** Another agent holds the lock. `flock(LOCK_EX)` blocks
until released. No timeout — the agent waits.

**Foreign staged files.** Exit code 2. Agent retries on heartbeat. By then the
other agent's commit may have completed (clearing the index) or the human
may have cleaned up.

**Lint failure.** `LintRunner.run()` raises `SystemExit`. Files remain staged
for the agent to fix and retry.

**Path B/C gate.** Functional files on main without human approval. Exit with
guidance. Path B: human approves a small commit. Path C: human approves the
commit and the agent dispatches `/next-review-commits` with the resulting SHAs.

## See Also

- docs/global/software-development/design/session-file-scoping.md
- docs/global/software-development/policy/version-control-safety.md
