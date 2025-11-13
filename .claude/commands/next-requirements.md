---
description: Create requirements document for a subject (or next roadmap item)
---

You are now in **requirements generation mode**. Follow these steps to create a requirements document:

## Step 1: Determine Subject

**If subject provided as argument**:
- Use that subject as-is
- Generate slug from subject (kebab-case, max 50 chars)
  - Example: "File upload captions" → `file-upload-captions`
  - Example: "Redis adapter improvements" → `redis-adapter-improvements`

**If NO subject provided**:
1. Read `todos/roadmap.md`
2. Find the first unchecked item (line starting with `- [ ]`)
3. Extract the full description text as subject
4. Generate slug from description

## Step 2: Create Folder Structure

1. Create directory: `todos/{slug}/`
2. Check if `todos/{slug}/requirements.md` already exists
3. If it exists:
   - Read the existing requirements
   - Ask user if they want to:
     - Skip to `/next-implementation` (already has requirements)
     - Regenerate the requirements (overwrite)
     - Abort

## Step 3: Generate Requirements Document

Create `todos/{slug}/requirements.md` with this structure:

```markdown
# {Title}

> **Created**: {current date}
> **Status**: 📝 Requirements

## Problem Statement

What problem does this solve? What pain points does it address? Why is this needed now?

## Goals

**Primary Goals**:
- Goal 1 (must have)
- Goal 2 (must have)

**Secondary Goals** (if applicable - think KISS and YAGNI):
- Nice-to-have 1
- Nice-to-have 2

## Non-Goals

What is explicitly OUT of scope for this work? (KISS & YAGNI principles)

- Non-goal 1
- Non-goal 2

## User Stories / Use Cases

### Story 1: {User Role}
As a {user role}, I want to {action} so that {benefit}.

**Acceptance Criteria**:
- [ ] Criterion 1
- [ ] Criterion 2

### Story 2: {User Role}
As a {user role}, I want to {action} so that {benefit}.

**Acceptance Criteria**:
- [ ] Criterion 1
- [ ] Criterion 2

## Technical Constraints

- Constraint 1 (e.g., must work with existing architecture patterns)
- Constraint 2 (e.g., must support multi-computer setup)
- Constraint 3 (e.g., must maintain backward compatibility)

## Success Criteria

How will we know this is successful?

- [ ] Measurable criterion 1 (e.g., "All file uploads include caption support")
- [ ] Measurable criterion 2 (e.g., "Tests pass on all machines")
- [ ] Measurable criterion 3 (e.g., "Zero regressions in existing functionality")

## Open Questions

- Question 1?
- Question 2?

## References

- Related roadmap items
- Architecture docs (docs/architecture.md, CLAUDE.md)
- External resources
```

**Important Guidelines**:

- Be clear and concise - focus on WHAT and WHY, not HOW
- Make requirements measurable and verifiable
- Call out constraints explicitly
- Link to relevant architecture docs
- Consider multi-computer implications if applicable
- Follow TeleClaude's architecture patterns

## Step 4: Update Roadmap

If subject came from roadmap:
1. Mark the roadmap item as in-progress: Change `- [ ]` to `- [>]`

## Step 5: Summary Report

Report to user:

```
✅ Requirements created: todos/{slug}/requirements.md

📋 Subject: {subject}
🎯 Primary goals: {count}
✅ Success criteria: {count}

Next step: Run /next-implementation {slug}
```

## Important Notes

- Always generate a meaningful slug (not generic names like "item-1")
- Read the roadmap item carefully - it may have multi-line descriptions
- Requirements should be implementation-agnostic (no specific technical details yet)
- Focus on user value and business outcomes
- Keep it concise but comprehensive
