# Todo Breakdown Assessment - Requirements

## Problem Statement

Large todos with complex input result in requirements.md and implementation-plan.md files that exceed what a single AI session can complete. Currently, next-prepare only checks if files exist - no complexity assessment happens, leading to failed or incomplete deliveries.

## Core Objective

Add a "Definition of Ready" assessment step to next-prepare that evaluates todos from input.md and breaks complex ones into smaller, independently deliverable child todos.

---

## Definition of Ready Criteria (AI-Centric)

The assessment evaluates whether a todo can succeed given AI constraints:

### 1. Single-Session Completability
Can one AI session complete this before context exhaustion? If the scope requires reading too many files or making too many changes, it won't fit.

### 2. Verifiability
Are success criteria concrete and checkable by AI? Can tests prove completion? No ambiguous "it should feel right" criteria.

### 3. Atomicity
Can the work be committed without breaking the system? Are there clean boundaries?

### 4. Scope Clarity
Are requirements unambiguous? Does the AI have enough context to make pragmatic decisions without escalating?

### 5. Uncertainty Level
Is the technical approach known, or does this need exploration first?

---

## Behavior Specification

### Trigger
input.md exists in todo folder AND state.json has no `breakdown.assessed` property.

### Assessment Process
AI reads input.md and evaluates against Definition of Ready criteria.

### If Breakdown Needed
1. Create child todo folders: `todos/{slug}-1/`, `todos/{slug}-2/`, etc.
2. Each child gets input.md with scoped content from parent
3. Update `todos/dependencies.json`: children have no deps, parent depends on all children
4. Update `todos/roadmap.md`: add children before parent in correct order
5. Create `todos/{slug}/breakdown.md`: reasoning artifact documenting the split
6. Update `todos/{slug}/state.json`: `{ "breakdown": { "assessed": true, "todos": ["slug-1", "slug-2"] } }`
7. Parent todo stops here (no requirements.md or implementation-plan.md)

### If No Breakdown Needed
1. Create `todos/{slug}/breakdown.md`: reasoning why no split needed
2. Update `todos/{slug}/state.json`: `{ "breakdown": { "assessed": true, "todos": [] } }`
3. Proceed to create requirements.md from input.md

---

## State Schema Addition

```json
{
  "breakdown": {
    "assessed": true,
    "todos": ["child-slug-1", "child-slug-2"]
  }
}
```

- `assessed`: boolean - whether assessment has been performed
- `todos`: string[] - child todo slugs (empty if no breakdown needed)

---

## File Artifacts

| File | Purpose | Created When |
|------|---------|--------------|
| `input.md` | Raw input/brain dump | Initial todo creation |
| `breakdown.md` | Reasoning artifact | After assessment |
| `state.json` | Machine state | After assessment |
| `requirements.md` | Structured requirements | Only if no breakdown |
| `implementation-plan.md` | Execution plan | Only if no breakdown |

---

## Success Criteria

- [ ] next_prepare() detects input.md and checks for breakdown.assessed in state.json
- [ ] AI assessment uses Definition of Ready criteria (not arbitrary numbers)
- [ ] Complex todos result in child folders with input.md each
- [ ] Dependencies correctly set: parent depends on children
- [ ] Roadmap updated with children in execution order
- [ ] breakdown.md created as reasoning artifact
- [ ] state.json updated with breakdown status
- [ ] Simple todos proceed to requirements.md creation normally
- [ ] next-prepare.md command has clear instructions for AI performing assessment

---

## Non-Goals

- No changes to next-work state machine
- No subtask concept within a single todo
- No new dependency mechanism (use existing dependencies.json)
- No time estimates or sprint concepts
