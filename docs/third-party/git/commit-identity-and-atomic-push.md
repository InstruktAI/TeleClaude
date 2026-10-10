---
description: Git commit identity, explicit tree and parent construction, and all-or-nothing remote reference updates.
---

# Commit identity and atomic reference publication

A Git commit identifies a tree and its parents. `git commit-tree` creates a
commit from an existing tree and explicit parent objects. Multiple parents form
a merge commit; the tree is still supplied explicitly. A new parent, tree, or
commit metadata produces a different commit identity.

Fast-forward publication requires the current remote branch tip to be an
ancestor of the proposed new tip. A concurrent remote advancement can therefore
reject a push without modifying the proposed commit object.

`git push --atomic` requests that the remote update every specified reference or
none of them. A remote without atomic-push support rejects the operation. Atomic
Git reference updates do not include an external hosting service's release API.

## Sources

- https://git-scm.com/docs/git-commit-tree
- https://git-scm.com/docs/git-push
- https://git-scm.com/docs/gitworkflows
