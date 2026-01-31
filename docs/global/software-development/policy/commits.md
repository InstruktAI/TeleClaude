---
description: Commitizen format, attribution, when to commit. Atomic commits, hooks
  verify quality.
id: software-development/policy/commits
scope: domain
type: policy
---

# Commits — Policy

## Required reads

- @~/.teleclaude/docs/software-development/policy/code-quality.md

## Rules

Pre-commit hooks enforce tests, linting, and formatting automatically.

Only commit when ALL conditions are met:

- Change is atomic and complete
- Code works (hooks will verify)
- No debug/temp code
- All tests pass
- No lint violations

Use commitizen format:

```
type(scope): subject

🤖 Generated with [TeleClaude](https://github.com/InstruktAI/TeleClaude)

Co-Authored-By: TeleClaude <noreply@instrukt.ai>
```

**Valid types:**

- `feat` - New feature
- `fix` - Bug fix
- `refactor` - Code restructuring
- `docs` - Documentation changes
- `test` - Test additions or updates
- `chore` - Maintenance tasks
- `perf` - Performance improvements

**Scope:** Component or area affected (optional but recommended)

**Subject:** Clear, concise description in imperative mood

- One logical change per commit
- Keep commits small and focused
- Commit message explains WHY, not WHAT (code shows what)
- Never commit broken code
- Never use `--no-verify` to bypass hooks
- Update or add tests when behavior changes.
- Include migration notes when schema or data shape changes.
- Avoid committing generated artifacts unless explicitly required.
- Squash noisy fixups before merge to keep history readable.

## Rationale

- Consistent commits enable reliable rollbacks and audits.
- Commit messages drive automated release notes and changelogs.

## Scope

- Applies to all repositories and all contributors (human or AI).

## Enforcement

- Pre-commit hooks and CI validate format, tests, and linting.
- Reviews reject commits that violate the format or atomicity.

## Exceptions

- Emergency production fixes may allow minimal commits with a follow-up cleanup task.
