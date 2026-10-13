---
description: Git detached HEAD semantics and the fetch-refspec rule that determines argument-less pull integration.
---

# Detached Checkout and Pull

`git checkout --detach <commit>` makes HEAD name the commit directly and leaves
branch references intact. Detached HEAD remains writable: creating a commit
moves HEAD to that new commit. It is not an immutable-checkout control.

For `git pull` without explicit refspecs, Git selects integration from the current
branch's merge configuration when available. Otherwise a globbing fetch refspec
selects no branch for integration, while a non-globbing configuration can select
the first refspec's remote branch. A detached single-branch clone can therefore
advance on an ordinary pull; checking detached posture alone does not establish
pull refusal.

The standard all-branches fetch mapping is
`+refs/heads/*:refs/remotes/origin/*`. Pull behavior also depends on effective Git
configuration and command arguments. Explicit branch selection remains an
operator-directed integration request.

## Sources

- https://git-scm.com/docs/git-checkout#_detached_head
- https://git-scm.com/docs/git-pull#_default_behaviour
