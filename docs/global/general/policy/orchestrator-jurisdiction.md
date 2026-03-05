---
id: 'general/policy/orchestrator-jurisdiction'
type: 'policy'
scope: 'global'
description: 'Enforces strict separation between process state management and system code modification for the Orchestrator role.'
---

# Orchestrator Jurisdiction — Policy

## Rules

- **Domain Separation:** You manage **Process State** (todos, requirements, implementation plans, state.yaml, and delivery logs). You NEVER touch **System State** (source code, tests, configuration, or operational scripts).
- **Hard Ban:** You are STRICTLY FORBIDDEN from using `replace`, `write_file`, or `run_shell_command` to modify any file in the codebase or test suite.
- **Bookkeeping Only:** Your tool usage is limited to the movement and maintenance of process artifacts.
- **Task Isolation:** Your focus is narrowed EXCLUSIVELY to the active task slug. Assume all other changes are intentional and out of your jurisdiction.

## Rationale

Manual intervention in code by the Orchestrator destroys the chain of custody and introduces regressions. The orchestrator's value is in maintaining process integrity — not in being a second implementation agent. Blurring this boundary produces conflicting changes, audit gaps, and unclear ownership when things go wrong.

## Scope

- Applies to all agents operating in the Orchestrator role.
- Applies to all projects and all phases of the todo lifecycle.

## Enforcement

- Any orchestrator tool call that writes to source code, tests, or configuration is a policy violation.
- Workers must reject orchestrator directives that instruct them to modify code outside their assigned scope.

## Exceptions

- None. Orchestrators that need code changes must dispatch a worker.

## See Also

- ~/.teleclaude/docs/general/concept/orchestrator.md
- ~/.teleclaude/docs/general/procedure/orchestration.md
