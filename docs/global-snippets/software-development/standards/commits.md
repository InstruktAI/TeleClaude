---
description:
  Commitizen format, attribution, when to commit. Atomic commits, hooks
  verify quality.
id: software-development/standards/commits
requires:
  - software-development/standards/code-quality
scope: domain
type: policy
---

# Commit Standards

## Requirements

@docs/global-snippets/software-development/standards/code-quality.md

## Pre-Commit Hooks

Pre-commit hooks enforce tests, linting, and formatting automatically.

## When to Commit

Only commit when ALL conditions are met:

- Change is atomic and complete
- Code works (hooks will verify)
- No debug/temp code
- All tests pass
- No lint violations

## Commit Message Format

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

## Commit Hygiene

- One logical change per commit
- Keep commits small and focused
- Commit message explains WHY, not WHAT (code shows what)
- Never commit broken code
- Never use `--no-verify` to bypass hooks
