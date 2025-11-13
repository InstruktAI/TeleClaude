---
description: Create implementation plan from requirements with parallel task support
---

You are now in **implementation planning mode**. Follow these steps to create an actionable implementation plan:

## Step 1: Determine Subject

**If subject provided as argument**:
- Use that subject to find folder
- Generate slug if needed (kebab-case)

**If NO subject provided**:
1. Find most recent folder in `todos/` (by modification time)
2. Use that as the subject folder

## Step 2: Load Requirements

1. Read `todos/{slug}/requirements.md`
2. If file doesn't exist:
   - Error: "Requirements not found. Run /next-requirements {subject} first"
   - Stop execution

## Step 3: Analyze Requirements for Implementation

Extract actionable work from requirements document:

1. **Goals** → Core features to implement
2. **User Stories** → Specific functionality
3. **Technical Constraints** → Technical tasks
4. **Success Criteria** → Testing and verification tasks

## Step 4: Create Implementation Plan

Create `todos/{slug}/implementation-plan.md` with this structure:

```markdown
# {Title} - Implementation Plan

> **Requirements**: todos/{slug}/requirements.md
> **Status**: 🚧 Ready to Implement
> **Created**: {current date}

## Implementation Groups

**IMPORTANT**: Tasks within each group CAN be executed in parallel. Groups must be executed sequentially.

### Group 1: Foundation & Setup
*These tasks can run in parallel*

- [ ] **PARALLEL** Install required dependencies
- [ ] **PARALLEL** Update configuration files (config.yml, .env)
- [ ] **PARALLEL** Create new directories and scaffold files

### Group 2: Core Implementation
*These tasks can run in parallel*

- [ ] **PARALLEL** Create `path/to/new_file.py` - Purpose and key functions
- [ ] **PARALLEL** Modify `path/to/existing.py` - Specific changes needed
- [ ] **DEPENDS: Group 1** Integrate components together

### Group 3: Testing
*These tasks can run in parallel*

- [ ] **PARALLEL** Write unit tests for component X in `tests/unit/test_x.py`
- [ ] **PARALLEL** Write integration tests for feature Y in `tests/integration/test_y.py`
- [ ] **DEPENDS: Group 2** Run full test suite and fix failures

### Group 4: Documentation & Polish
*These tasks can run in parallel*

- [ ] **PARALLEL** Update README.md if user-facing changes (installation, usage, commands, requirements)
- [ ] **PARALLEL** Update docs/architecture.md if architecture changed
- [ ] **DEPENDS: Group 3** Run `make format && make lint && make test`

### Group 5: Review & Finalize
*These tasks must run sequentially*

- [ ] Review created (automated via `/review {slug}`)
- [ ] Review feedback handled (automated by spawned agent)

### Group 6: Deployment
*These tasks must run sequentially*

- [ ] Test locally with `make restart && make status`
- [ ] Switch to main: `cd ../.. && git checkout main`
- [ ] Merge worktree branch: `git merge {slug}`
- [ ] Push and deploy: `/deploy`
- [ ] Verify deployment on all computers
- [ ] Cleanup worktree: `/remove_worktree_prompt {slug}`

## Task Markers

- `**PARALLEL**`: Can execute simultaneously with other PARALLEL tasks in same group
- `**DEPENDS: GroupName**`: Requires all tasks in GroupName to complete first
- `**SEQUENTIAL**`: Must run after previous task in group completes

## Implementation Notes

### Key Design Decisions
- Design decision 1
- Design decision 2

### Potential Blockers
- Blocker 1
- Blocker 2

### Files to Create/Modify

**New Files**:
- `path/to/file.py` - Purpose

**Modified Files**:
- `path/to/existing.py` - Changes

## Success Verification

Before marking complete, verify all requirements success criteria:

- [ ] Success criterion 1 (from requirements.md)
- [ ] Success criterion 2
- [ ] All tests pass (`make lint && make test`)
- [ ] Code formatted and linted
- [ ] Deployed to all machines

## Completion

- [ ] All task groups completed
- [ ] Success criteria verified
- [ ] Mark roadmap item as complete (`[x]`)

---

**Usage with /next-work**: The next-work command will execute tasks group by group, running PARALLEL tasks simultaneously when possible.
```

**Task Grouping Guidelines**:

1. **Group by Dependency**: Tasks that don't depend on each other go in same group
2. **Mark Parallel Tasks**: Use `**PARALLEL**` prefix for tasks that can run simultaneously
3. **Specify Dependencies**: Use `**DEPENDS: GroupX**` to indicate cross-group dependencies
4. **Logical Phases**: Group similar work together (setup, implementation, testing, deployment)
5. **Right-Sized**: Each group should be completable in one focused session
6. **Specific Paths**: Always include full file paths
7. **Clear Done State**: Each task should have obvious completion criteria

**Task Types by Parallelizability**:

**Highly Parallel** (can usually run together):
- Creating new files
- Writing unit tests for different modules
- Updating independent config files
- Adding new functions to different files

**Sometimes Parallel**:
- Modifying different parts of same file
- Writing tests for interdependent modules

**Sequential** (must run in order):
- Integration tasks that combine components
- Deployment steps
- Tasks that modify the same code section

## Step 5: Summary Report

Report to user:

```
✅ Implementation plan created: todos/{slug}/implementation-plan.md

📋 Total groups: {count}
🔄 Parallel tasks: {count}
➡️  Sequential tasks: {count}
🎯 First group: {first group name} ({task count} tasks)

Next step: Run /next-work {slug}
```

## Important Notes

- **CRITICAL**: Mark tasks with `**PARALLEL**` if they can run simultaneously
- Group tasks logically - don't create artificial dependencies
- Each task should map to concrete code changes
- Include file paths and line numbers when useful
- Testing is NOT optional - always include test tasks
- Keep tasks atomic (one clear thing to do)
- Link back to requirements document
