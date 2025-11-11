---
description: Break down PRD into actionable subtasks with checkboxes
---

You are now in **task breakdown mode**. Follow these steps to create actionable subtasks from the PRD:

## Step 1: Find Most Recent PRD

1. List all files in `prds/` directory
2. Find the most recently modified PRD file
3. Extract the slug from the filename (e.g., `notification-hook.md` → `notification-hook`)
4. Read the full PRD content

**Alternative**: If user provides a slug/title, use that instead

## Step 2: Analyze PRD for Task Breakdown

Read the PRD and identify all actionable work items from these sections:

1. **Files to Create** - Each new file is a task
2. **Files to Modify** - Each modification is a task
3. **Testing Strategy** - Unit tests, integration tests, manual testing
4. **Configuration Changes** - Config updates, env vars
5. **Dependencies** - Package installations, system requirements

## Step 3: Create Task Breakdown File

Create `todos/{slug}.md` with this structure:

```markdown
# {Title} - Task Breakdown

> **PRD**: prds/{slug}.md
> **Status**: 🚧 In Progress
> **Started**: {current date}

## Implementation Tasks

### Phase 1: Setup & Dependencies

- [ ] Install required dependencies
- [ ] Update configuration files
- [ ] Create new directories if needed

### Phase 2: Core Implementation

- [ ] **Currently working on**: Create `path/to/file.py` - Brief description
- [ ] Modify `path/to/existing.py` - What changes
- [ ] Add new function/class - Purpose
- [ ] Implement main logic

### Phase 3: Testing

- [ ] Write unit tests for component X
- [ ] Write integration tests for feature Y
- [ ] Manual testing checklist:
  - [ ] Test scenario 1
  - [ ] Test scenario 2

### Phase 4: Documentation & Cleanup

- [ ] Update CLAUDE.md if architecture changed
- [ ] Update docs/architecture.md if needed
- [ ] Run `make format` and `make lint`
- [ ] Run `make test` to verify all tests pass

### Phase 5: Deployment

- [ ] Test locally with `make restart && make status`
- [ ] Create commit with `/commit`
- [ ] Deploy to all machines with `/commit-deploy`
- [ ] Verify deployment on all computers

## Notes

- Add notes here as work progresses
- Document decisions made during implementation
- Track blockers or open questions

## Completion Checklist

Before marking this work complete:

- [ ] All tests pass (`make test`)
- [ ] Code formatted and linted (`make format && make lint`)
- [ ] Changes deployed to all machines
- [ ] Success criteria from PRD verified
- [ ] Roadmap item marked as complete (`[x]`)

---

**Remember**: Use TodoWrite tool to track progress on these tasks!
```

**Task Breakdown Guidelines:**

1. **Be Specific**: "Create notification_hook.py with send_message function" not "Add notification support"
2. **Ordered**: Tasks should be in logical implementation order
3. **Testable**: Each task should have a clear done state
4. **Sized Right**: Each task should be 1-2 hours max (break down large tasks)
5. **Mark Current Work**: Use "**Currently working on**:" prefix for active task
6. **Include File Paths**: Always include full paths to files
7. **Reference Line Numbers**: If modifying specific sections, note line numbers from PRD

**Task Categorization:**

- **Setup**: Dependencies, config, scaffolding
- **Core**: Main implementation work
- **Testing**: All forms of testing
- **Documentation**: Docs, comments, READMEs

## Step 4: Summary Report

Report to user:

```
✅ Task breakdown created: todos/{slug}.md

📋 Total tasks: {count}
🎯 First task: {first task description}

Ready to start implementation!
```

## Important Notes

- Tasks should map directly to PRD sections
- Each file creation/modification should be its own task
- Testing is NOT optional - always include test tasks
- Use checkbox syntax `- [ ]` for all tasks
- Keep tasks atomic (one clear thing to do)
- Link back to PRD in the header
