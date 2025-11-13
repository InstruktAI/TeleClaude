---
description: Process code review feedback by auto-fixing issues in worktree
---

You are now in **review processing mode**. This handles review feedback automatically.

**INPUT**: Subject slug (branch name, e.g., "file-upload-captions")

## Step 1: Read Review

Read `todos/{slug}/review.md` to understand:

- All critical issues that MUST be fixed
- Minor issues that SHOULD be fixed if straightforward
- Auto-fix assessment (can this be automated?)

## Step 2: Check Auto-Fix Viability

Look for "Auto-Fix Assessment" section in review.md:

**If "Can auto-fix: NO"**:

- Report to user: "Review requires manual intervention - see todos/{slug}/review.md"
- Exit without making changes

**If "Can auto-fix: YES"**:

- Proceed with automated fixes

## Step 3: Switch to Worktree

Change to the worktree directory:

```bash
cd worktrees/{slug}/
```

Verify you're in the correct directory before proceeding.

## Step 4: Fix Issues

Work through issues in priority order:

1. **Critical Issues** (MUST fix all):

   - Read each issue carefully
   - Apply the suggested fix
   - Verify the fix addresses the root cause

2. **Minor Issues** (fix if straightforward):
   - Only fix if solution is obvious
   - Skip if requires architectural changes

**Important**:

- Make focused, surgical changes
- Don't refactor unrelated code
- Follow coding directives from review

## Step 5: Run Tests

After making fixes, run the full test suite:

```bash
make lint && make test
```

**If tests pass**:

- Proceed to Step 6

**If tests fail**:

- Fix test failures
- Re-run tests until all pass
- If stuck after 2 attempts:
  - Add note to review.md: "Failed to auto-fix - tests failing: {error summary}"
  - Mark as needing manual intervention
  - Exit

## Step 6: Update Implementation Plan

Mark the review feedback as handled:

```markdown
# In todos/{slug}/implementation-plan.md

### Group 5: Review & Finalize

- [x] Review created (automated via `/review {slug}`)
- [x] Review feedback handled (automated via `/process-review {slug}`)
```

Update the checkbox from `- [ ]` to `- [x]` for "Review feedback handled".

## Step 7: Commit Changes

Create ONE commit with:

- All code fixes
- Updated checkbox in implementation-plan.md

Use `/commit` command (NOT `/deploy` - we're in a worktree).

The commit message should be:

```
fix(review): address code review feedback for {slug}

Applied automated fixes from code review:
- Fixed critical issues from review
- Addressed minor issues where straightforward
- All tests passing

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

## Step 8: Report Success

Report to user:

```
✅ Review feedback processed for {slug}

Fixed issues:
- {count} critical issues resolved
- {count} minor issues addressed

Tests: PASSING
Commit: {commit hash}

Ready for merge to main.
```

## Important Notes

- **Work in worktree only** - don't touch main branch
- **One commit total** - code fixes + checkbox update
- **Don't merge or deploy** - that happens later in /next-work
- **If stuck, bail out** - mark manual intervention needed
- **Follow review exactly** - don't add scope creep
- **Run tests before commit** - never commit failing code

## Error Handling

If any step fails:

1. Document the failure in review.md notes section
2. Mark "Manual intervention required: {specific reason}"
3. Don't commit partial fixes
4. Report to user what went wrong
