---
description: 'Commitizen format, attribution, when to commit. Atomic commits, hooks verify quality.'
visibility: 'public'
---

# Commits — Policy

## Rules

This is the canonical source of commit behavior. Other docs may reference it, but must not redefine commit policy.

Use commitizen format:

```
type(scope): subject

🤖 Generated with [TeleClaude](https://github.com/InstruktAI/TeleClaude)

Co-Authored-By: TeleClaude <noreply@instrukt.ai>
```

**Valid types:**

All Committizen types are allowed.

**Scope:** Component or area affected (optional but recommended)

**Subject:** Clear, concise description in imperative mood

- One logical change per commit
- Keep commits small and focused
- Commit message explains WHY, not WHAT (code shows what)
- Update or add tests when behavior changes.
- Include migration notes when schema or data shape changes.
- Squash noisy fixups before merge to keep history readable.
- **`[skip ci]` for automation bookkeeping.** Any commit pushed to origin/main that contains only scaffolding, roadmap updates, or other non-code bookkeeping MUST include `[skip ci]` in the commit subject line. CI runs are reserved for actual code delivery. The integration push from `trees/_integration/` is the only push that should trigger CI.
- **Commit first, then route review.** Committing is part of normal autonomous
  agent work. An agent that has completed a coherent change commits it through
  the sealed interface without asking the human for commit permission. In
  `telec code commit --approved`, `--approved` means the agent has passed the
  commit gate and owns the pathspec-scoped commit; it does not mean the human
  approved the commit.
- Before committing on shared `main`, run bare `telec code commit` to surface
  the gate card, then commit with `telec code commit --approved "<message>"`
  using the scoped pathspec the tool resolves. New untracked files require
  explicit inclusion through `telec code add <path>` or `--include <path>`.
- Post-commit review is routed by the committed diff, not by pre-commit
  permission. Functional code/tests are committed first; if independent review
  is warranted, the agent states the recommendation and dispatches review if
  the human stays silent for the policy-defined timer. Governed contracts
  (documentation snippets) and agent artifacts require independent review after
  commit. Pure non-governed bookkeeping needs no review.

## Rationale

- Consistent commits enable reliable rollbacks and audits.
- Commit messages drive automated release notes and changelogs.
- Asking before routine commits shifts technical stewardship back to the human
  and leaves completed work unrecorded. The safety boundary is the sealed commit
  gate plus post-commit review routing, not a human permission prompt.

## Scope

- Applies to all repositories and all contributors.

## Enforcement

`telec code commit` is the canonical commit interface. The wrapper handles workspace scoping, staging, and pre-commit hooks automatically; direct git operations are blocked and self-document at the error path.

Commit guidance, CLI help, agent addenda, and project-specific designs must not
describe `--approved` as human approval or require a pre-commit human decision.
They may reference this policy and document mechanics, but the commit-first
rule lives here.

## Exceptions

- Emergency production fixes may allow minimal commits with a follow-up cleanup task.
