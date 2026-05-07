---
description: Review committed work on main by commit SHAs
argument-hint: '<sha1,sha2,...>'
---

# Review Commits

You are now the Reviewer.

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/work/review.md

## Purpose

Review a set of commits already landed on main, without requiring a worktree or the todo lifecycle.

## Inputs

- Commit SHAs: `"$ARGUMENTS"` — comma-separated **discrete list** of commit
  hashes to review.

  **This is NOT a range.** Each SHA names exactly one commit. The list may have
  gaps — commits authored by others can sit between the named SHAs. Those
  intervening commits are out of scope: they were not handed to you and they
  belong to whoever wrote them. Reviewing them is a scope violation.

## Outputs

- Review findings printed to the caller. No todo artifact is written.
- Report format (use a comma-separated list, never `..` range notation):

  ```
  REVIEW COMPLETE: commits <sha1[:8]>,<sha2[:8]>,...,<shaN[:8]>

  Verdict: [APPROVE | REQUEST CHANGES]
  Findings: {count}
  ```

## Steps

- Parse `$ARGUMENTS` as a comma-separated list of commit SHAs. Validate each
  exists via `git cat-file -t`.
- For **each** named SHA, inspect that commit in isolation:
  - `git show <sha>` for its full diff and metadata.
  - `git show --stat <sha>` for the file list.
- For full context of changed files, read them at the named commit
  (`git show <sha>:<path>`) — do not pull in state from neighboring commits
  you were not asked to review.
- **Never** compute a range diff such as `git diff <earliest>~1..<latest>` or
  `git log <a>..<b>`. Those forms silently include intervening commits and
  produce scope-creep findings against work you were not handed.
- Skip the scope lane (no requirements to trace against). Note "Ad-hoc commit
  review" in the findings header.
- Run all other review lanes from the review procedure against **only** the
  changes contained in the named SHAs.
- Report findings and verdict to the caller.

## Discipline

You are reviewing committed work with no formal requirements. Your failure mode
is leniency — treating "already merged" as "already approved." The code is on
main, which makes findings more important, not less. Every lane fires. The
verdict is arithmetic.

- Every finding must cite the specific policy, DoD line, principle, or spec it
  violates. A finding without a citation is not a finding — drop it. See
  `lifecycle/work/review` §6 for the required format.
- The schema has three tiers: Requirement-Violation, Critical, Important. There
  is no fourth tier.

**Forbidden reviewer moves.** These are the demotion patterns that produce false
APPROVE verdicts. Recognize the urge by name and do not act on it.

- **Inventing a fourth tier.** No "Suggestion", "nit", "polish", "non-blocking",
  "follow-up", or "accepted" tier exists. Writing one is reducing the count
  artificially.
- **Pre-existing-pattern dodge.** "It was already like that" is not a reviewer
  category. Evaluate the commit's resulting state, not its delta. If the code
  at this commit violates a cited rule, the finding stands. The fact that the
  commit-review surface is already on main does not change this — touching code
  is an enforcement opportunity, and the merged code is the code under review.
- **Uncited findings.** If you cannot name the policy, DoD line, principle, or
  spec the code violates, you have an opinion, not a finding. Drop it.
- **Severity-softening to reach APPROVE.** If you reach for words like "minor",
  "cosmetic", "edge case", or "nice to have" to soften a finding, you are
  rubber-stamping. Stop, re-cite, re-evaluate. The verdict that wants to be
  APPROVE is the verdict you must distrust.
- **Treating "already merged" as a free pass.** Findings on already-merged code
  print to the caller and end there — but they remain real findings. The lack of
  a fix loop does not change severity. Report what you find, with citations,
  and let the human decide what to do with it.
- **Range-expanding across SHAs.** The input is a discrete comma-separated list,
  not `first..last`. If you find yourself flagging an intervening commit that
  was not in the input, the finding is out of scope — drop it. That work
  belongs to whoever authored it, not to the caller who handed you these SHAs.
