---
description: Find out what to do next and continue WIP or break down todo story into requirements + implementation plan. Start here if asked to do work.
---

You are now in **WORK mode**. Your output is ALWAYS working code that is covered by tests.

Follow these steps to find out what to do next:

## Step 1: Fix Bugs FIRST

1. Open `todos/bugs.md` to see if there are any open bugs (unchecked items).
2. If there are open bugs, pick the first one and work on fixing it.
3. Work on fixing all open bugs before moving on.

## Step 2: Determine Subject

**If subject provided as argument**:
- Use that subject to find `todos/{slug}/` folder

**If NO subject provided**:
1. Read `todos/roadmap.md`
2. Find the item marked as in-progress (`- [>]`)
3. If no in-progress item, find first unchecked item (`- [ ]`)
4. Extract description and generate slug
5. Use that as the subject

## Step 2.5: Create or Switch to Worktree

**CRITICAL**: All work must be done in an isolated worktree to avoid conflicts.

1. **Check if worktree already exists**:
   - Run `/list_worktrees_prompt`
   - Look for worktree with branch name matching `{slug}`

2. **If worktree exists**:
   - Switch to existing worktree directory: `cd worktrees/{slug}`
   - Continue with existing work

3. **If worktree does NOT exist**:
   - Run `/create_worktree_prompt {slug}` (no port offset needed)
   - This will:
     - Create `worktrees/{slug}/` directory
     - Create git branch `{slug}`
     - Set up isolated environment
     - Switch to the worktree directory
   - Continue with new work

**Important**: Always verify you're in the worktree directory before proceeding with implementation tasks.

## Step 3: Check Requirements & Implementation Plan Exist

1. Check if `todos/{slug}/requirements.md` exists
   - If NOT: Run `/next-requirements {subject}`
   - Wait for it to complete, then continue

2. Check if `todos/{slug}/implementation-plan.md` exists
   - If NOT: Run `/next-implementation {slug}`
   - Wait for it to complete, then continue

## Step 4: Execute Implementation Plan

1. Read `todos/{slug}/requirements.md` to understand the goals
2. Read `todos/{slug}/implementation-plan.md` to see the task breakdown

### Task Execution Strategy

**For each task group** (sequentially):

1. **Identify parallel vs sequential tasks**:
   - Tasks marked with `**PARALLEL**` can run simultaneously
   - Tasks marked with `**SEQUENTIAL**` or `**DEPENDS:**` must run in order

2. **Execute parallel tasks**:
   ```
   If multiple tasks in group are marked **PARALLEL**:
   - Create separate tool calls for each parallel task
   - Execute all tool calls in a single message
   - Wait for all to complete before continuing
   ```

3. **Execute sequential tasks**:
   - Run one at a time
   - Wait for completion before next task

4. **Complete task workflow** (per task):
   - Make code changes
   - Run tests (`make lint && make test`)
   - Update checkbox from `- [ ]` to `- [x]` in `todos/{slug}/implementation-plan.md`
   - Commit ONCE with both code changes AND todo update: `/commit`

   **IMPORTANT**:
   - Use `/commit` (not `/commit-deploy`) while in worktree
   - Each commit = one completed task (code + todo checkbox)
   - Only use `/commit-deploy` after merging to main branch

### Parallel Execution Example

```markdown
### Group 2: Core Implementation
- [ ] **PARALLEL** Create handler.py
- [ ] **PARALLEL** Create validator.py
- [ ] **DEPENDS: Group 1** Integrate components
```

**Execution**:
1. Run "Create handler.py" AND "Create validator.py" in parallel (single message, multiple tool calls)
2. Wait for both to complete
3. Run "Integrate components" sequentially

## Step 5: Continue Until Complete

1. Work through all task groups sequentially
2. Execute parallel tasks within each group simultaneously
3. Mark tasks as complete in implementation-plan.md
4. When all implementation tasks done (Groups 1-4), trigger review
5. When review is complete, proceed to deployment

**After completing all implementation tasks (before deployment):**

Run `/review {slug}` - this will:
- Analyze code changes against requirements and implementation plan
- Create `todos/{slug}/review.md` with detailed analysis
- Spawn agent to auto-fix issues in worktree
- Agent commits fixes and marks "Review feedback handled" checkbox

**You can continue to next work item** while review agent works in parallel.

## Step 5.5: Merge Worktree and Cleanup

**After all tasks complete and review feedback handled**:

1. **Ensure all changes committed in worktree**:
   - Verify `git status` is clean
   - All tasks should be committed (you've been doing `/commit` per task)

2. **Switch back to main branch**:
   - `cd` to project root (outside worktree): `cd ../..`
   - `git checkout main`

3. **Merge worktree branch to main**:
   - `git merge {slug}`
   - Resolve any conflicts if needed

4. **Push and deploy to all machines**:
   - Run `/commit-deploy` to push to GitHub and deploy to all machines
   - No new commit needed - merge already brought all commits to main
   - This pushes everything and deploys to production

5. **Remove worktree**:
   - Run `/remove_worktree_prompt {slug}`
   - This removes both the worktree directory and branch

6. **Verify cleanup**:
   - Run `/list_worktrees_prompt` to confirm worktree removed
   - Check main branch has all changes

## Step 6: If No Implementation Plan Exists

If requirements.md exists but implementation-plan.md doesn't:
1. Run `/next-implementation {slug}`
2. Wait for completion
3. Return to Step 4

If neither exists:
1. Run `/next-requirements {subject}`
2. Run `/next-implementation {slug}`
3. Return to Step 4

## Important Notes

- **Worktree isolation**: ALWAYS work in a worktree to avoid conflicts with main branch
- **Parallel execution**: When possible, execute independent tasks simultaneously
- **Testing is mandatory**: All code changes must have passing tests
- **Commit per task**: One commit = code changes + checkbox update (NOT two separate commits)
- **Use /commit in worktree**: Create local commits with `/commit` (no deployment yet)
- **Use /commit-deploy after merge**: Only push and deploy after merging to main
- **Check dependencies**: Always verify `**DEPENDS:**` requirements are met
- **Update roadmap**: Mark items in-progress (`[>]`) and complete (`[x]`)
- **Ask questions**: If requirements unclear, ask before implementing

## Work Session Template

For each work session:

1. ✅ Check bugs first
2. 🌳 Create/switch to worktree
3. 📖 Read requirements.md
4. 📋 Read implementation-plan.md
5. 🎯 Identify current task group
6. ⚡ Execute parallel tasks simultaneously

**Per task completion**:
7. 🧪 Run `make lint && make test`
8. ✔️  Update checkbox in implementation-plan.md
9. 💾 `/commit` (one commit with code + checkbox)

**After all tasks in worktree**:
10. 🔍 Review: `/review {slug}` (spawns agent, continues in parallel)
11. ✅ Wait for review feedback handled
12. 🔀 Merge to main: `cd ../.. && git checkout main && git merge {slug}`
13. 🚀 Deploy: `/commit-deploy` (now push to everyone)
14. 🧹 Cleanup: `/remove_worktree_prompt {slug}`

## Error Handling

If a task fails:
1. Log the error in implementation-plan.md notes section
2. Fix the issue
3. Re-run the task
4. Only mark complete when successful

If blocked:
1. Document blocker in implementation-plan.md
2. Ask user for clarification
3. Don't proceed until unblocked
