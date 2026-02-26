---
description: 'Two-track bug handling: inline for internal discovery, maintenance for external reports.'
id: 'software-development/procedure/bugs-handling'
scope: 'domain'
type: 'procedure'
---

# Bugs Handling — Procedure

## Goal

Fix bugs the moment you discover them. For external bug reports (GitHub Issues), a
periodic maintenance routine handles triage and resolution in a controlled worktree.

There is no bugs backlog. There is no `bugs.md`. Internal bugs are fixed inline.
External bugs arrive via GitHub Issues and are processed by the maintenance runner.
For CLI bug intake, default to `telec bugs report` (scaffold + dispatch); use
`telec bugs create` only when explicitly requested to stage a bug without dispatch.

## Track 1: Inline (Internal Discovery)

### Preconditions

- You discovered a bug during your current work.

### Steps

1. **Assess scope.** Can you fix this in a few minutes without derailing your current
   task? Most bugs encountered during active work are small — a wrong condition, a
   missing guard, a stale reference.

2. **Fix inline.** Fix it right where you are, on whatever branch you are on. Apply the
   minimal fix, verify via commit hooks (lint + unit tests), commit, continue.

3. **If the bug is too large for inline fixing**, it is not a bug — it is a work item.
   Create `todos/{slug}/input.md` with the issue details and add it to
   `todos/roadmap.yaml`. Do not create a separate bugs file.

4. **Never log a bug and move on.** That middle ground — "I'll note it for later" —
   creates noise that goes stale. Either fix it or promote it. There is no third option.

### Outputs

- Bug fixed and committed on the current branch, or
- New work item in `todos/` with the issue promoted to a roadmap entry.

## Track 2: Maintenance (External Reports)

### Preconditions

- Bug reports exist as GitHub Issues (labeled `bug`).
- The maintenance runner (jobs/maintenance.py) triggers periodically.

### Steps

1. **Pull issues.** `gh issue list --label bug --state open` to discover actionable reports.
2. **Triage.** Skip stale, duplicates, issues already with linked PRs.
3. **Dispatch.** The `next-bugs` worker fixes each issue in `.bugs-worktree`, creates a
   PR referencing the issue (`gh pr create --closes #N`).
4. **Review.** Accumulated PRs are reviewed and merged on a controlled cadence.

### Outputs

- PRs created for each resolved issue, referencing the GitHub Issue number.
- Issues auto-closed when PRs merge.

## Recovery

- If you cannot reproduce an inline bug, investigate briefly. If it remains elusive,
  create a work item with your investigation notes.
- If your fix introduces a regression, fix the regression immediately.
- For external bugs that cannot be reproduced, comment on the issue asking for more
  information. Let the `no-response` bot handle stale reporter silence.
