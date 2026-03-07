# Breakdown: proficiency-to-expertise

## Assessment

**Splitting not needed.** This is one behavior — replace a flat proficiency field
with a structured expertise model — flowing through its consumers. The input.md
lists 15+ touchpoints, but most are 2-5 line edits (field renames, format string
changes, test updates). Total estimated change: ~300 lines of production code + tests.

The detail in the input (exact file paths, line numbers, before/after code) means
the approach is fully known. What remains is mechanical execution.

Splitting model from consumers would create a half-working codebase and inter-todo
coordination overhead that exceeds the work itself.

## DOR Gate Assessment

| Gate | Status | Evidence |
|------|--------|----------|
| 1. Intent & success | Pass | Clear problem statement with concrete schema, injection, and config surface changes |
| 2. Scope & size | Pass | One coherent behavior, ~300 lines total, detailed approach known |
| 3. Verification | Pass | Tests identified per component in input.md |
| 4. Approach known | Pass | Exact file paths, line numbers, before/after code in input.md |
| 5. Research complete | Auto-pass | No new third-party dependencies |
| 6. Dependencies | Pass | No roadmap blockers |
| 7. Integration safety | Pass | Backward-compatible migration — old proficiency field still accepted |
| 8. Tooling impact | Pass | Config wizard updates explicitly scoped in input.md |

**Score: 8 / 10** — Status: **pass**
