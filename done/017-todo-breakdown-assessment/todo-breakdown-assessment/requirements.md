# Todo Breakdown Assessment - Requirements

## Problem Statement

Large todos with complex input result in requirements.md and implementation-plan.md files that exceed what a single AI session can complete. Currently, next-prepare only checks if files exist - no complexity assessment happens, leading to failed or incomplete deliveries.

## Core Objective

Add a "Definition of Ready" assessment step to next-prepare that evaluates todos from input.md and splits complex ones into smaller, independently deliverable todos.

---

## Definition of Ready Criteria (AI-Centric)

The assessment evaluates whether a todo can succeed given AI constraints:

### 1. Single-Session Completability
Can one AI session complete this before context exhaustion? If the scope requires reading too many files or making too many changes, it won't fit.

### 2. Verifiability
Are success criteria concrete and checkable by AI? Can tests prove completion?

### 3. Atomicity
Can the work be committed without breaking the system? Are there clean boundaries?

### 4. Scope Clarity
Are requirements unambiguous? Does the AI have enough context to make pragmatic decisions?

### 5. Uncertainty Level
Is the technical approach known, or does this need exploration first?

---

## Behavior Specification

### Trigger
input.md exists in todo folder AND state.json has no `breakdown.assessed` property.

### Assessment Process
AI reads input.md and evaluates against Definition of Ready criteria.

### If Breakdown Needed
1. Create new todo folders: `todos/{slug}-1/`, `todos/{slug}-2/`, etc.
2. Each gets input.md with scoped content
3. Update `todos/dependencies.json`: `{slug}` depends on `[{slug}-1, {slug}-2]`
4. Update `todos/roadmap.md`: add new todos before `{slug}` in execution order
5. Create `todos/{slug}/breakdown.md`: reasoning artifact documenting the split
6. Update `todos/{slug}/state.json`: `{ "breakdown": { "assessed": true, "todos": ["{slug}-1", "{slug}-2"] } }`
7. `{slug}` becomes a container (no requirements.md or implementation-plan.md)

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
    "todos": ["{slug}-1", "{slug}-2"]
  }
}
```

- `assessed`: boolean - whether assessment has been performed
- `todos`: string[] - slugs of todos created from split (empty if no breakdown)

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
- [ ] AI assessment uses Definition of Ready criteria
- [ ] Complex todos result in new todo folders with input.md each
- [ ] Dependencies correctly set: original depends on split todos
- [ ] Roadmap updated with split todos in execution order
- [ ] breakdown.md created as reasoning artifact
- [ ] state.json updated with breakdown status
- [ ] Simple todos proceed to requirements.md creation normally
- [ ] next-prepare.md command has clear instructions for AI performing assessment

---

## Prompt Engineering Principles

**The holy grail: a perfect work package that an AI can complete without confusion or overload.**

### Objective-Focused
- State the action to take
- Positive framing: "Create todos" tells AI exactly what to do
- Each instruction leads to a concrete action

### Minimal
- Every sentence serves execution
- Only include what changes AI behavior
- Concise beats comprehensive

### Clear Decision Points
- Binary outcomes: "If X, do A. Otherwise, do B."
- Explicit criteria for each branch
- AI reads once, knows what to do

### Single Responsibility
- Each section handles one concern
- Separation: assessment logic lives in next-prepare, orchestration in prime-orchestrator

### Trust the AI
- State the objective, AI figures out mechanics
- AI is a skilled executor

---

## Non-Goals

- Changes to next-work state machine
- Subtask concept within a single todo
- New dependency mechanism (use existing dependencies.json)
- Time estimates or sprint concepts
