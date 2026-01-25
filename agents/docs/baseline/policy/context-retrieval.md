# Context Retrieval Policy — Policy

Call `teleclaude__get_context` as your first action when:

- Starting any task or assigned a role
- Instructed to "read up on", "understand", or research something
- Writing documentation, creating patterns, or scaffolding projects
- Making architectural decisions or choosing between approaches
- Reviewing code, writing tests, or handling errors
- Debugging, refactoring, or investigating issues
- Orchestrating other AI workers or following procedures
- Working with unfamiliar patterns or before committing changes

## Rationale

Context-gathering is mandatory. Immediate context prevents drift from established policies, procedures, and architectural decisions.

## Scope

This policy applies to all AI agents across all projects and tasks.
