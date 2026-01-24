---
name: next-code-simplifier
description: Simplify code for clarity, consistency, and maintainability while preserving all functionality. Use after completing a coding task or after passing code review to polish the implementation.
---

This skill simplifies code for clarity, consistency, and maintainability while preserving exact functionality. It applies project-specific best practices and prioritizes readable, explicit code over overly compact solutions.

## Context to Gather

Before simplifying, read:

- `AGENTS.md` or `CLAUDE.md` - Project coding standards
- `~/.teleclaude/docs/development/coding-directives.md` - Coding standards
- Related code to understand existing patterns

## Core Responsibilities

### 1. Preserve Functionality

Never change what the code does - only how it does it. All original features, outputs, and behaviors must remain intact.

### 2. Apply Project Standards

Follow the established coding standards including:

- Proper import sorting and module patterns
- Function declaration conventions
- Explicit return type annotations
- Proper component patterns with explicit types
- Error handling patterns
- Consistent naming conventions

### 3. Enhance Clarity

Simplify code structure by:

- Reducing unnecessary complexity and nesting
- Eliminating redundant code and abstractions
- Improving readability through clear variable and function names
- Consolidating related logic
- Removing unnecessary comments that describe obvious code
- **Avoiding nested ternary operators** - prefer switch statements or if/else chains
- Choosing clarity over brevity - explicit code is often better than compact code

### 4. Maintain Balance

Avoid over-simplification that could:

- Reduce code clarity or maintainability
- Create overly clever solutions that are hard to understand
- Combine too many concerns into single functions or components
- Remove helpful abstractions that improve code organization
- Prioritize "fewer lines" over readability
- Make the code harder to debug or extend

### 5. Focus Scope

Only refine code that has been recently modified or touched in the current session, unless explicitly instructed to review a broader scope.

## Refinement Process

1. Identify the recently modified code sections
2. Analyze for opportunities to improve clarity and consistency
3. Apply project-specific best practices and coding standards
4. Ensure all functionality remains unchanged
5. Verify the refined code is simpler and more maintainable
6. Document only significant changes that affect understanding

## Output Format

For each simplification:

1. **Location**: File path and line range
2. **Issue**: What makes the current code complex or unclear
3. **Change**: The simplified version
4. **Rationale**: Why this improves clarity/maintainability

Group changes by file. Prioritize high-impact simplifications.

Ensure all code meets the highest standards of clarity and maintainability while preserving complete functionality.
