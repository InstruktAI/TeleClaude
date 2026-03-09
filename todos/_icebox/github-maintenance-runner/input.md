# GitHub Maintenance Runner

## Context

We have established an inline-first bug paradigm: bugs discovered by AI agents during active work are fixed immediately, on the current branch, with no backlog file or dispatch ceremony.

However, **external bug reports** from users (via GitHub Issues) require a different workflow. These arrive cold — no active session context, no agent already looking at the code. They need a controlled environment, isolated from active development on main, with proper PR-based integration.

## The Feature

A periodic maintenance routine that:

1. Pulls open GitHub Issues labeled `bug`
2. Triages and prioritizes them (skip stale, duplicates, issues already with linked PRs)
3. Dispatches a `next-bugs` worker for each actionable issue
4. The worker fixes the bug in `.bugs-worktree`, creates a PR referencing the issue (`--closes #N`)
5. Accumulated PRs are reviewed and merged on a controlled cadence

## Architecture

```
Cron Runner (hourly) — existing infrastructure
  └── MaintenanceJob (jobs/maintenance.py) — NEW
       ├── gh issue list --label bug --state open --json number,title,body,labels
       ├── Filter: skip stale, skip duplicates, skip issues with linked PRs
       ├── Pre-work: assess severity, check if issue maps to known code areas
       └── For each actionable issue:
            └── Dispatch next-bugs worker in .bugs-worktree
                 ├── Tools: get_context (doc retrieval) + gh CLI
                 ├── git checkout main && git pull origin main (in worktree)
                 ├── Create feature branch: bugs/issue-{N}
                 ├── Fix, verify (lint + tests), commit
                 └── gh pr create --base main --title "fix: ..." --body "Closes #{N}"
```

## Artifacts to Create/Modify

### Create

- `jobs/maintenance.py` — MaintenanceJob class (Schedule.DAILY or HOURLY, pulls issues, dispatches workers)
- GitHub repo configuration — install bots, set up label conventions

### Rewrite

- `agents/commands/next-bugs.md` — from backlog triage to GitHub Issue worker (receives issue context, fixes in worktree, creates PR)
- `docs/global/software-development/procedure/bugs-handling.md` — split into two sections: inline (internal) and maintenance (external via GitHub)

### Update

- `docs/global/software-development/concept/fixer.md` — remove `.bugs-worktree` from inline flow, reference maintenance flow for external bugs
- `docs/global/general/procedure/checkpoint.md` — remove `.bugs-worktree` from inline capture rules
- `docs/global/general/procedure/memory-management.md` — remove `.bugs-worktree` from routing table
- `teleclaude/core/next_machine/core.py` — remove bugs sentinel block, `has_pending_bugs` function, `POST_COMPLETION["next-bugs"]`
- `teleclaude/mcp/handlers.py` — remove `next-bugs` from `state_machine_commands` set
- `tests/unit/test_next_machine_hitl.py` — remove `test_next_prepare_hitl_bugs_sentinel_detected`

### Keep

- `.bugs-worktree/` in `.gitignore` — it's the maintenance worktree now
- `.bugs-worktree` convention — but exclusively for the maintenance flow, never for inline fixes

## GitHub Ecosystem Tools (free for public repos)

- **actions/stale** — auto-labels issues with no activity after N days, auto-closes after warning period
- **dessant/lock-threads** — locks old closed issues/PRs to prevent necro-threads
- **github/issue-labeler** — auto-labels issues based on body/title pattern matching
- **probot/no-response** — closes issues where reporter doesn't respond to maintainer questions

## Design Decisions to Make

1. **Maintenance frequency** — DAILY at a quiet hour (e.g., 4 AM) or HOURLY with dedup?
2. **PR merge strategy** — auto-merge if tests pass, or always human/AI review first?
3. **Issue triage depth** — should the manager attempt complexity assessment, or just dispatch everything under a size threshold?
4. **Branch strategy** — one branch per issue (`bugs/issue-42`) or batch branch (`bugs/maintenance-YYMMDD`)?
5. **Worker concurrency** — one issue at a time sequentially, or parallel workers for independent issues?
6. **next-maintain integration** — should this live under `next-maintain` (currently a stub) or stay as its own `maintenance.py` job?

## Dependencies

- Jobs runner infrastructure (exists, documented in `docs/project/design/architecture/jobs-runner.md`)
- `gh` CLI authenticated on the machine (exists)
- `.bugs-worktree` convention (exists)
- Inline bugs cleanup (in progress — remove `.bugs-worktree` from inline docs)

## Out of Scope

- Deploying our full agent stack to GitHub Actions (decided against — too complex, our doc snippet system isn't portable)
- Auto-assigning issues to humans
- Feature requests or non-bug issues
