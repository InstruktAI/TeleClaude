---
description: 'Review discrete commits already on main by SHA, without a worktree or the todo lifecycle.'
needs_domain_baseline: true
visibility: 'public'
---

# Review Commits — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/review-build.md
- @~/.teleclaude/docs/software-development/policy/definition-of-done-lanes.md
- @~/.teleclaude/docs/software-development/policy/quality-predicate-registry.md
- @~/.teleclaude/docs/software-development/policy/process-change-authority.md

## Goal

Review a discrete set of commits already landed on main, identified by SHA, without
requiring a worktree or the todo lifecycle. Lanes, severity schema, citation rules,
and verdict arithmetic come from the review procedure above; this procedure adds only
the commit-scoping discipline.

## Preconditions

- `$ARGUMENTS` is a comma-separated **discrete list** of commit hashes — not a range.
  Each SHA names exactly one commit; commits authored by others may sit between the
  named SHAs and are out of scope.

## Steps

### 1. Validate the input as a discrete SHA list

Parse `$ARGUMENTS` as a comma-separated list of commit SHAs. Confirm each exists via
`git cat-file -t`. The list may have gaps — intervening commits are not yours to review.

### 2. Inspect each named commit in isolation

For **each** SHA: `git show <sha>` for its full diff and metadata, `git show --stat <sha>`
for the file list. For full context of a changed file, read it at the named commit
(`git show <sha>:<path>`) — do not pull in state from neighboring commits.

**Never** compute a range diff (`git diff <earliest>~1..<latest>`, `git log <a>..<b>`).
Range forms silently include intervening commits and produce scope-creep findings against
work you were not handed.

### 3. Run the review lanes against only the named changes

Skip the scope lane — there are no requirements to trace against; note "Ad-hoc commit
review" in the findings header. Run all other lanes from the review procedure against
**only** the changes contained in the named SHAs.

For the tests lane, independently apply every `TQ-*` predicate triggered by the
named diffs and record evidence or a reasoned `N/A` for every ID.

### 4. Report

Report findings and verdict to the caller using a comma-separated commit list, never
`..` range notation:

```
REVIEW COMPLETE: commits <sha1[:8]>,<sha2[:8]>,...,<shaN[:8]>

Verdict: [APPROVE | REQUEST CHANGES]
Findings: {count}
```

## Outputs

- Review findings printed to the caller. No todo artifact is written.

## Recovery

Reviewing already-merged code with no formal requirements invites leniency — the failure
mode is treating "already merged" as "already approved." The code is on main, which makes
findings more important, not less. Beyond the review procedure's general discipline, refuse
these commit-review-specific dodges:

- **Pre-existing-pattern dodge.** "It was already like that" is not a category. Evaluate the
  commit's resulting state, not its delta. Touching code is an enforcement opportunity.
- **Already-merged free pass.** Findings on merged code print to the caller and end there,
  but they remain real findings — the absence of a fix loop does not lower severity.
- **Range-expanding across SHAs.** If you find yourself flagging a commit not in the input
  list, the finding is out of scope — drop it.
