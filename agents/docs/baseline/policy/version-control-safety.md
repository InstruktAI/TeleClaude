# Version Control Safety Policy — Policy

## Rule

- Never use `git checkout`, `git restore`, `git reset`, `git clean`, or delete files unless explicitly instructed by the user.
- If your task requires editing a file that already has uncommitted changes, stop and ask before modifying it.
- Only modify files you intentionally touched as part of the request.

## Rationale

- Prevents data loss and accidental overwrite of concurrent work.
- Keeps changes auditable and attributable to the correct agent or user.

## Scope

- Applies to all repositories and all agents, across all tasks.

## Enforcement or checks

- If uncommitted changes exist in a file you need to edit, pause and ask for direction.
- Do not auto-clean or discard changes to make commits succeed.

## Exceptions or edge cases

- None.
