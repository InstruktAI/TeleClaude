---
description: Review discrete commits already on main by SHA, without a worktree or the todo lifecycle.
---

# Review Commits — Procedure

## Required reads

- @~/.teleclaude/docs/software-development/procedure/lifecycle/review.md

## Goal

Review a discrete set of commits already landed on main, identified by SHA,
without requiring a worktree or the todo lifecycle. The SHA list supplies the
review context; the shared review procedure supplies the review judgment.

## Preconditions

- `$ARGUMENTS` is a comma-separated discrete list of commit hashes, not a
  range.
- Each SHA names exactly one commit. Commits authored by others may sit between
  the named SHAs and remain out of scope.

## Steps

### 1. Validate the discrete SHA list

Parse `$ARGUMENTS` as a comma-separated list. Confirm every SHA exists with
`git cat-file -t`. Gaps between named commits are valid.

### 2. Inspect each named commit in isolation

For each SHA, inspect its complete diff, metadata, and file list:

```bash
git show <sha>
git show --stat <sha>
```

Read full changed-file context at the named commit with
`git show <sha>:<path>`. Do not use neighboring commit state.

Never compute a range diff or range log. Range forms silently include commits
the reviewer was not given.

### 3. Execute the shared review contract

Execute `software-development/procedure/lifecycle/review` in full.

For this invocation:

- The target is the discrete SHA list.
- The applicable contracts are the governing policies, principles, specs, and
  resulting behavior touched by the named commits.
- The lifecycle scope lane is skipped because no prepared requirements exist.
- Every other lane runs according to the shared catalog's trigger conditions,
  against only the named changes.
- The doc-hygiene lane runs whenever a named commit changes a doc snippet.
- The doc-first paradigm lane runs because this is an ad-hoc commit review with
  no prepare artifacts.

For the tests lane, apply every `TQ-*` predicate triggered by the named diffs
and record evidence or a reasoned `N/A`.

### 4. Return the commit-review result

Print the complete structured findings and verdict to the caller. Do not select
a todo, write a todo artifact, or stamp lifecycle state.

Use comma-separated commit notation in the target line, never range notation:

```text
REVIEW COMPLETE: commits <sha1[:8]>,<sha2[:8]>,...,<shaN[:8]>
```

## Outputs

- Review findings printed to the caller.
- Verdict printed to the caller.
- No todo artifact or lifecycle stamp.

## Recovery

Already-merged code receives no leniency:

- A pre-existing pattern does not excuse a cited violation in the resulting
  state of a touched file.
- Merge state does not lower finding severity.
- A finding against a commit outside the supplied SHA list is out of scope and
  is dropped.

If a supplied SHA cannot be resolved, report the blocker and stop. Never expand
the review to nearby commits.
