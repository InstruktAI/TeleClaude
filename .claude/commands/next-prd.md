---
description: Create PRD for next roadmap item and break it down into tasks
---

You are now in **PRD generation mode**. Follow these steps to create a Product Requirements Document for the next roadmap item:

## Step 1: Find Next Roadmap Item

1. Read `todos/roadmap.md`
2. Find the first unchecked item (line starting with `- [ ]`)
3. Extract the full description text
4. Generate a slug from the description (kebab-case, max 50 chars)
   - Example: "Create notification hook" → `notification-hook`
   - Example: "Add Redis adapter" → `redis-adapter`

## Step 2: Check if PRD Exists

1. Check if `prds/{slug}.md` already exists
2. If it exists:
   - Read the existing PRD
   - Ask user if they want to:
     - Skip to `/next-breakdown` (already has PRD)
     - Regenerate the PRD (overwrite)
     - Abort

## Step 3: Generate Comprehensive PRD

Create `prds/{slug}.md` with this structure:

```markdown
# {Title}

## Overview

Brief 2-3 sentence summary of what this feature/change is and why it matters.

## Problem Statement

What problem does this solve? What pain points does it address?

## Goals

- Primary goal 1
- Primary goal 2
- Secondary goals if applicable, but think KISS and YAGNI!

## Non-Goals

What is explicitly OUT of scope for this work? KISS & YAGNI!

## Technical Approach

### High-Level Design

Describe the overall approach at a conceptual level.

### Key Components

1. **Component 1**: Description of what it does
2. **Component 2**: Description of what it does

### Data Model Changes

Any database schema changes, new tables, new fields, etc.

### API/Interface Changes

Any new functions, classes, adapters, or external APIs.

### Configuration Changes

Any new config fields in config.yml, .env, etc.

## Implementation Details

### Files to Create

- `path/to/new_file.py` - Purpose

### Files to Modify

- `path/to/existing_file.py` - What changes are needed

### Dependencies

Any new libraries to install, system requirements, etc.

## Testing Strategy

### Unit Tests

What unit tests need to be created?

### Integration Tests

What integration scenarios need testing?

### Manual Testing

How to manually verify this works?

## Rollout Plan

1. Development and testing
2. Deployment considerations
3. Rollback strategy if needed

## Success Criteria

- [ ] Criterion 1 (measurable/verifiable)
- [ ] Criterion 2
- [ ] Criterion 3

## Open Questions

- Question 1?
- Question 2?

## References

- Related docs, issues, PRDs
- External resources
```

**Important Guidelines:**

- Be comprehensive but concise - aim for 200-400 lines
- Focus on WHAT and WHY, not just HOW
- Call out dependencies and risks explicitly
- Make success criteria measurable
- Link to relevant architecture docs (docs/architecture.md, CLAUDE.md)
- Consider multi-computer implications if applicable
- Follow TeleClaude's architecture patterns (Observer, Module-level Singleton, etc.)

## Step 4: Call Next Breakdown

After creating the PRD, automatically invoke `/next-breakdown` to generate the task breakdown:

```
SlashCommand("/next-breakdown")
```

## Important Notes

- Always generate a meaningful slug (not generic names like "item-1")
- Read the roadmap item carefully - it may have multi-line descriptions
- Reference existing architecture docs when writing technical approach
- Don't skip the `/next-breakdown` step - that's where actionable tasks are created
- Mark the roadmap item as in-progress (`- [x]`) once PRD is created
