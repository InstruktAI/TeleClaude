---
name: next-type-design-analyzer
description: Analyze type design quality and invariants. Use when introducing new types, during PR creation with data models, or when refactoring type designs.
---

This skill analyzes type designs to ensure strong, clearly expressed invariants and well-encapsulated interfaces.

## Context to Gather

Before analyzing, read:

- The type definitions being reviewed
- Related types and their relationships
- How the types are used throughout the codebase
- Existing type patterns in the project

## Core Mission

Evaluate type designs with a critical eye toward invariant strength, encapsulation quality, and practical usefulness. Well-designed types are the foundation of maintainable, bug-resistant software systems.

## Analysis Framework

When analyzing a type:

### 1. Identify Invariants

Examine the type to identify all implicit and explicit invariants:

- Data consistency requirements
- Valid state transitions
- Relationship constraints between fields
- Business logic rules encoded in the type
- Preconditions and postconditions

### 2. Evaluate Encapsulation (Rate 1-10)

- Are internal implementation details properly hidden?
- Can the type's invariants be violated from outside?
- Are there appropriate access modifiers?
- Is the interface minimal and complete?

### 3. Assess Invariant Expression (Rate 1-10)

- How clearly are invariants communicated through the type's structure?
- Are invariants enforced at compile-time where possible?
- Is the type self-documenting through its design?
- Are edge cases and constraints obvious from the type definition?

### 4. Judge Invariant Usefulness (Rate 1-10)

- Do the invariants prevent real bugs?
- Are they aligned with business requirements?
- Do they make the code easier to reason about?
- Are they neither too restrictive nor too permissive?

### 5. Examine Invariant Enforcement (Rate 1-10)

- Are invariants checked at construction time?
- Are all mutation points guarded?
- Is it impossible to create invalid instances?
- Are runtime checks appropriate and comprehensive?

## Output Format

```
## Type: [TypeName]

### Invariants Identified
- [List each invariant with a brief description]

### Ratings
- **Encapsulation**: X/10
  [Brief justification]

- **Invariant Expression**: X/10
  [Brief justification]

- **Invariant Usefulness**: X/10
  [Brief justification]

- **Invariant Enforcement**: X/10
  [Brief justification]
```
