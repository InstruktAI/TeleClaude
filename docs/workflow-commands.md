# Workflow Commands

This document describes the automated workflow commands for managing development tasks in TeleClaude.

## Overview

The workflow automation consists of two commands that work together to transform high-level roadmap items into actionable, tracked tasks:

1. **`/next-prd`** - Generates a Product Requirements Document for the next roadmap item
2. **`/next-breakdown`** - Breaks down a PRD into specific, checkboxed tasks

## File Structure

```
teleclaude/
├── todos/
│   ├── roadmap.md              # High-level feature stories (unchecked items)
│   ├── {feature-name}.md       # Task breakdown with checkboxes (generated)
│   └── README.md
├── prds/
│   └── {feature-name}.md       # Product Requirements Document (generated)
└── .claude/
    └── commands/
        ├── next-prd.md         # Command to generate PRD
        └── next-breakdown.md   # Command to generate tasks
```

## Workflow

### Step 1: Add Item to Roadmap

Edit `todos/roadmap.md` and add a high-level feature description:

```markdown
# Roadmap

1. [ ] Create notification hook that sends feedback to channel when Claude starts
2. [ ] Add support for multi-user sessions
3. [ ] Implement session recording playback
```

### Step 2: Generate PRD

Run the command:

```
/next-prd
```

**What it does:**

1. Reads `todos/roadmap.md`
2. Finds the first unchecked item (`[ ]`)
3. Generates a slug (e.g., "notification-hook")
4. Creates `prds/notification-hook.md` with comprehensive PRD
5. Automatically calls `/next-breakdown`

**PRD Contents:**

- Overview and problem statement
- Goals and non-goals
- Technical approach
- Implementation details (files to create/modify)
- Testing strategy
- Rollout plan
- Success criteria

### Step 3: Task Breakdown (Automatic)

The `/next-breakdown` command is automatically invoked and:

1. Reads the most recently created PRD
2. Extracts actionable tasks from PRD sections
3. Creates `todos/notification-hook.md` with:
   - Categorized tasks (Setup, Core, Testing, Documentation, Deployment)
   - Checkboxes for each task
   - First task marked as "Currently working on"
   - File paths and line numbers

**Task File Structure:**

```markdown
# Notification Hook - Task Breakdown

> **PRD**: prds/notification-hook.md
> **Status**: 🚧 In Progress
> **Started**: 2025-11-11

## Implementation Tasks

### Phase 1: Setup & Dependencies
- [ ] Create teleclaude/core/notification_hook.py

### Phase 2: Core Implementation
- [ ] **Currently working on**: Implement send_message function
- [ ] Bootstrap adapter_client in hook
- [ ] Add randomized message templates

### Phase 3: Testing
- [ ] Write unit tests for notification hook
- [ ] Test integration with adapter_client

### Phase 4: Documentation & Cleanup
- [ ] Update README.md if user-facing changes
- [ ] Update docs/architecture.md if architecture changed
- [ ] Run `make format` and `make lint`

### Phase 5: Deployment
- [ ] Deploy with `/deploy`
```

### Step 4: Implementation

As you work through tasks:

1. **Use TodoWrite tool** to track progress in your Claude Code session
2. **Update checkboxes** in `todos/{feature-name}.md` as you complete tasks
3. **Move "Currently working on"** marker to the next task
4. **Add notes** in the Notes section for decisions/blockers

### Step 5: Completion

When all tasks are complete:

1. Mark all checkboxes as `[x]`
2. Verify success criteria from PRD
3. Mark roadmap item as complete in `todos/roadmap.md`: `[x]`
4. Deploy changes with `/deploy`

## Command Reference

### `/next-prd`

**Purpose**: Generate PRD for next roadmap item and break it into tasks

**Usage**: Simply type `/next-prd` (no arguments)

**Output**:
- `prds/{slug}.md` - Comprehensive PRD
- `todos/{slug}.md` - Task breakdown (via automatic `/next-breakdown` call)

**Behavior**:
- If PRD already exists, asks whether to skip/regenerate/abort
- Generates meaningful slug from roadmap description
- Marks first task as "Currently working on"

### `/next-breakdown`

**Purpose**: Break down PRD into actionable tasks

**Usage**:
- Automatic: Called by `/next-prd`
- Manual: `/next-breakdown` (uses most recent PRD)
- Manual with specific PRD: `/next-breakdown {slug}`

**Output**:
- `todos/{slug}.md` - Task breakdown file

**Behavior**:
- Analyzes PRD sections (Files to Create/Modify, Testing, etc.)
- Creates categorized task list (Setup, Core, Testing, Docs, Deployment)
- Marks first task as current work item

## Best Practices

1. **Keep roadmap items high-level** - One sentence describing the feature/change
2. **Be specific in PRDs** - Include file paths, function names, technical details
3. **Size tasks appropriately** - Each task should be 1-2 hours max
4. **Update checkboxes as you go** - Don't wait until the end
5. **Use TodoWrite tool** - Track progress in your active Claude session
6. **Test incrementally** - Don't wait until all code is written
7. **Deploy often** - Use `/deploy` after each logical milestone

## Example: Full Workflow

```bash
# 1. Add to roadmap
echo "1. [ ] Add Redis health check endpoint" >> todos/roadmap.md

# 2. Generate PRD and tasks
/next-prd
# Creates: prds/redis-health-check.md
# Creates: todos/redis-health-check.md

# 3. Start implementation (Claude tracks with TodoWrite)
# Work through tasks in todos/redis-health-check.md
# Update checkboxes as you complete each task

# 4. Deploy when ready
/deploy

# 5. Mark complete
# Edit todos/roadmap.md: change [ ] to [x]
```

## Troubleshooting

**Q: What if I want to work on a different roadmap item (not the first unchecked)?**

A: Manually edit the roadmap to check off items you want to skip, or directly create a PRD file and run `/next-breakdown`.

**Q: Can I manually edit the task breakdown?**

A: Yes! The task files are meant to be living documents. Add tasks, reorder, update as needed.

**Q: What if I need to split a large task?**

A: Edit the task file and break it into sub-tasks using nested checkboxes:
```markdown
- [ ] Implement main feature
  - [ ] Sub-task 1
  - [ ] Sub-task 2
```

**Q: Should I commit the PRD and task files?**

A: Yes! Commit them so they're tracked in git and available across all development machines.
