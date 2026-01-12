# Implementation Plan: Todo Breakdown Assessment

## Overview

Add breakdown assessment step to next-prepare state machine. When input.md exists, AI evaluates complexity before creating requirements.md. Complex todos get split into children.

---

## Task 1: Update state.json schema and helpers

**File:** `teleclaude/core/next_machine.py`

Add functions to read/write breakdown state:

```python
def read_breakdown_state(cwd: str, slug: str) -> dict | None:
    """Read breakdown state from todos/{slug}/state.json."""

def write_breakdown_state(cwd: str, slug: str, assessed: bool, todos: list[str]) -> None:
    """Write breakdown state and commit."""
```

Update `DEFAULT_STATE` to include breakdown key structure.

- [ ] Add `read_breakdown_state()` function
- [ ] Add `write_breakdown_state()` function
- [ ] Update state reading to handle breakdown property

---

## Task 2: Update next_prepare() flow

**File:** `teleclaude/core/next_machine.py`

Insert breakdown check at the beginning of `next_prepare()`, after slug resolution:

```python
# After resolving slug, before checking requirements.md:

# Check for input.md
has_input = check_file_exists(cwd, f"todos/{slug}/input.md")
breakdown_state = read_breakdown_state(cwd, slug)

if has_input and (breakdown_state is None or not breakdown_state.get("assessed")):
    # Breakdown assessment needed
    if hitl:
        return format_hitl_guidance(
            f"Preparing: {slug}. Read todos/{slug}/input.md and assess Definition of Ready. "
            "If complex, create child todos. Then update state.json and create breakdown.md."
        )
    # Non-HITL: dispatch architect to assess
    return format_tool_call(...)

# If breakdown assessed and has children, parent is done
if breakdown_state and breakdown_state.get("todos"):
    return f"CONTAINER: {slug} was split into child todos: {breakdown_state['todos']}. Work on children first."
```

- [ ] Add input.md detection
- [ ] Add breakdown state check
- [ ] Add HITL guidance for breakdown assessment
- [ ] Add container detection (parent with children)
- [ ] Ensure flow proceeds to requirements.md only if breakdown.todos is empty

---

## Task 3: Update next-prepare.md command

**File:** `~/.agents/commands/next-prepare.md`

**CRITICAL: Apply Prompt Engineering Principles from requirements.md**

The prompt must be:
- Objective-focused (what to do, never what not to do)
- Minimal (only content needed for execution)
- Clear decision points (if X, do A; otherwise, do B)
- Trust the AI (state goal, let it figure out mechanics)

Add new section for breakdown assessment. Example structure (refine wording):

```markdown
## If input.md Exists

Assess whether this todo fits a single AI session.

**Criteria:** Can one session complete this with verifiable results and atomic commits?

**If too large:** Split into child todos.
1. Create `todos/{slug}-1/`, `todos/{slug}-2/` with input.md each
2. Add children to roadmap before parent
3. Set parent to depend on children in dependencies.json
4. Write breakdown.md with reasoning
5. Update state.json: `{ "breakdown": { "assessed": true, "todos": [...] } }`

**If appropriately scoped:** Proceed.
1. Write breakdown.md with reasoning
2. Update state.json: `{ "breakdown": { "assessed": true, "todos": [] } }`
3. Continue to requirements.md
```

- [ ] Add breakdown assessment section
- [ ] Apply prompt engineering principles: objective-focused, minimal, clear
- [ ] Review final wording for any prohibitions or fluff - remove them

---

## Task 4: Update prime-orchestrator.md

**File:** `~/.agents/commands/prime-orchestrator.md`

**CRITICAL: Apply Prompt Engineering Principles from requirements.md**

Minimal addition - only what orchestrator needs to know:

```markdown
## Preparation Flow

Discussion results go in `todos/{slug}/input.md`. Call `teleclaude__next_prepare(slug)` to assess and structure.
```

That's it. The orchestrator doesn't need to know breakdown mechanics - that's next-prepare's job.

- [ ] Add minimal preparation flow note
- [ ] Avoid duplicating breakdown logic (single responsibility)
- [ ] Review for any unnecessary content - remove it

---

## Task 5: Add helper for child todo creation

**File:** `teleclaude/core/next_machine.py`

Add function to create child todos (used by AI via direct file operations, but helper validates):

```python
def create_child_todo(cwd: str, parent_slug: str, child_suffix: str, input_content: str) -> str:
    """Create child todo folder with input.md. Returns child slug."""
```

This is optional - AI can create folders directly. But having a helper ensures consistency.

- [ ] Add `create_child_todo()` helper (optional)
- [ ] Or document that AI creates folders directly via Write tool

---

## Testing Strategy

### Manual Test 1: Complex Todo Breakdown
1. Create `todos/test-complex/input.md` with multi-domain scope
2. Run `teleclaude__next_prepare(slug="test-complex")`
3. Verify: AI creates child todos, breakdown.md, updates state.json
4. Verify: Children appear in roadmap, dependencies set correctly

### Manual Test 2: Simple Todo No-Breakdown
1. Create `todos/test-simple/input.md` with focused scope
2. Run `teleclaude__next_prepare(slug="test-simple")`
3. Verify: AI creates breakdown.md with "no split" reasoning
4. Verify: state.json has `{ breakdown: { assessed: true, todos: [] } }`
5. Verify: Proceeds to requirements.md creation

### Manual Test 3: Container Detection
1. After test-complex splits, call next_prepare on parent again
2. Verify: Returns "CONTAINER" message, doesn't re-assess

---

## Success Criteria Checklist

- [ ] next_prepare() detects input.md and checks for breakdown.assessed in state.json
- [ ] AI assessment uses Definition of Ready criteria (not arbitrary numbers)
- [ ] Complex todos result in child folders with input.md each
- [ ] Dependencies correctly set: parent depends on children
- [ ] Roadmap updated with children in execution order
- [ ] breakdown.md created as reasoning artifact
- [ ] state.json updated with breakdown status
- [ ] Simple todos proceed to requirements.md creation normally
- [ ] next-prepare.md prompt is objective-focused, minimal, clear (no prohibitions, no fluff)
- [ ] prime-orchestrator.md addition is minimal (one line if possible)
- [ ] All prompt updates reviewed: remove any "don't", "never", "avoid" language
