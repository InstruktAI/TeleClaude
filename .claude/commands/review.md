---
description: Review code changes for a feature branch and spawn agent to handle feedback
---

You are now in **review mode**. This analyzes code changes against requirements and spawns an agent to handle any feedback.

**INPUT**: Subject slug (branch name, e.g., "file-upload-captions")

## Step 1: Gather Context

Read the following files to understand what was supposed to be built:

1. **Requirements**: `todos/{slug}/requirements.md`
   - What problem was being solved?
   - What were the goals and success criteria?
   - What were the constraints?

2. **Implementation Plan**: `todos/{slug}/implementation-plan.md`
   - What tasks were completed?
   - What was the planned approach?

3. **Code Changes**: Run `git diff main..{slug}`
   - What files were changed?
   - How much code was added/removed?
   - What's the scope of changes?

## Step 2: Analyze Code Changes

Review the code changes against these criteria:

### Requirements Alignment
- ✅ Does implementation fulfill all requirements goals?
- ✅ Are all success criteria met?
- ✅ Are constraints respected?
- ❌ Missing functionality?
- ❌ Scope creep (implemented non-goals)?

### Code Quality
- ✅ Follows coding directives (`~/.claude/docs/development/coding-directives.md`)
- ✅ No inline/dynamic imports
- ✅ Type hints on all functions
- ✅ Functions < 50 lines, files < 500 lines
- ✅ Proper error handling
- ❌ Code smells (complexity, duplication, etc.)

### Architecture
- ✅ Follows TeleClaude patterns (from `CLAUDE.md`, `docs/architecture.md`)
- ✅ Observer pattern, module-level singletons, etc.
- ✅ Proper separation of concerns
- ❌ Breaks existing patterns?
- ❌ Creates tech debt?

### Testing
- ✅ Tests exist for new code
- ✅ Tests follow testing directives (`~/.claude/docs/development/testing-directives.md`)
- ✅ Tests pass (`make lint && make test`)
- ❌ Missing test coverage?
- ❌ Flaky tests?

### Security
- ❌ Command injection vulnerabilities?
- ❌ SQL injection risks?
- ❌ XSS vulnerabilities?
- ❌ Secrets in code?
- ❌ Unsafe file operations?

### Documentation
- ✅ CLAUDE.md updated if architecture changed?
- ✅ docs/architecture.md updated if needed?
- ✅ Docstrings for public functions?
- ❌ Missing or outdated docs?

## Step 3: Write Review

Create `todos/{slug}/review.md` with this structure:

```markdown
# Code Review: {Title}

> **Branch**: {slug}
> **Reviewed**: {current date}
> **Status**: {APPROVED / NEEDS CHANGES}

## Summary

Brief 2-3 sentence overview of what was implemented and overall assessment.

## Requirements Alignment

**Met**:
- ✅ Requirement 1
- ✅ Requirement 2

**Issues**:
- ❌ Issue 1: Description and suggested fix
- ⚠️  Warning 1: Minor concern

## Code Quality Issues

### Critical (Must Fix)
1. **[File:Line]**: Description
   - **Why**: Explanation
   - **Fix**: Specific guidance

### Minor (Should Fix)
1. **[File:Line]**: Description
   - **Suggestion**: Optional improvement

## Architecture Issues

(List any architecture concerns)

## Testing Issues

(List missing tests or test improvements needed)

## Security Issues

(List any security concerns - even if none, state "No security issues found")

## Documentation Needs

(List doc updates needed)

## Recommended Actions

1. Fix critical issues above
2. Address minor issues if time permits
3. Update documentation
4. Re-run `make lint && make test`

## Auto-Fix Assessment

**Can auto-fix**: {YES/NO}
- If YES: Agent will attempt to fix automatically
- If NO: Manual intervention required - {explain why}
```

## Step 4: Mark Review Created

Update `todos/{slug}/implementation-plan.md`:

Find the "Review & Finalize" group and mark:
```markdown
- [x] Review created
- [ ] Review feedback handled
```

## Step 5: Spawn Feedback Handler Agent

**If review found issues AND auto-fix is possible**:

Use Task tool to spawn agent with this prompt:

```
Handle code review feedback for {slug}.

Follow these steps:

1. Read todos/{slug}/review.md for all issues
2. Change directory: cd worktrees/{slug}/
3. Fix all critical issues listed in review
4. Address minor issues if straightforward
5. Run make lint && make test to verify fixes
6. If tests pass:
   a. Update checkbox in todos/{slug}/implementation-plan.md:
      - [x] Review feedback handled
   b. Commit with: /commit "Address code review feedback"
7. If tests fail:
   - Log error in todos/{slug}/review.md notes section
   - Mark as needing manual intervention

Work in the worktree directory. Do not merge or deploy - just fix and commit.
```

**If manual intervention needed**:
- Write in review.md: "Manual intervention required: {reason}"
- Don't spawn agent
- User will handle manually

## Step 6: Summary Report

Report to user:

```
✅ Code review completed: todos/{slug}/review.md

Status: {APPROVED / NEEDS CHANGES}
Critical issues: {count}
Minor issues: {count}

{If agent spawned}:
🤖 Spawned agent to handle feedback automatically
💡 You can continue to next work item in parallel

{If manual needed}:
⚠️  Manual intervention required - see review.md
```

## Important Notes

- Review is snapshot at time of running - code may change after
- Agent does ONE round of fixes only - if more issues arise, re-run /review
- Review does NOT know about worktrees - just analyzes git diff
- Spawned agent works in worktree, does not merge/deploy
- Original developer merges after confirming fixes
