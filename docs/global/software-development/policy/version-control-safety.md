---
id: software-development/policy/version-control-safety
type: policy
scope: domain
description: Safety rules for git operations and handling uncommitted work.
---

# Version Control Safety Policy — Policy

## Rules

- Never use `git checkout`, `git restore`, `git reset`, `git clean`, or delete files unless explicitly instructed by the user.
- If a file has uncommitted changes and you must edit it, ask first.
- Only modify files required by the request.

## Rationale

- Prevents accidental data loss and preserves ownership of in‑progress work.

## Scope

- Applies to all repositories and all agents.

## Enforcement

- Stop and ask before touching files with uncommitted changes.
- Never discard or overwrite uncommitted work unless told to.

## Exceptions

- None.
