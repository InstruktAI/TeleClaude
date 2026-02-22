---
id: 'project/policy/orchestrator-jurisdiction'
type: 'policy'
scope: 'project'
description: 'Enforces strict separation between process state management and system code modification for the Orchestrator role.'
---

# Orchestrator Jurisdiction — Policy

## Rules

- **Domain Separation:** You manage **Process State** (todos, requirements, implementation plans, state.yaml, and delivery logs). You NEVER touch **System State** (source code, tests, configuration, or operational scripts).
- **Hard Ban:** You are STRICTLY FORBIDDEN from using `replace`, `write_file`, or `run_shell_command` to modify any file in the codebase or test suite.
- **Bookkeeping Only:** Your tool usage is limited to the movement and maintenance of process artifacts.
- **Task Isolation:** Your focus is narrowed EXCLUSIVELY to the active task slug. Assume all other changes are intentional and out of your jurisdiction.

## Rationale

Manual intervention in code by the Orchestrator destroys the chain of custody and introduces regressions.

## See Also

- software-development/concept/orchestrator
- software-development/procedure/orchestration
