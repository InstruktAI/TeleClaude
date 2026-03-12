# Plan Review Findings: workflow-engine-refactor

## Critical

### C1: The plan narrows scope away from still-approved requirements, so the plan and requirements are no longer coherent

`requirements.md` still keeps language-aware code steps and a consolidated
workflow dispatch surface in scope
(`todos/workflow-engine-refactor/requirements.md:31`,
`todos/workflow-engine-refactor/requirements.md:35`,
`todos/workflow-engine-refactor/requirements.md:79`,
`todos/workflow-engine-refactor/requirements.md:82`,
`todos/workflow-engine-refactor/requirements.md:135`,
`todos/workflow-engine-refactor/requirements.md:137`).

The revised plan explicitly defers both workstreams
(`todos/workflow-engine-refactor/implementation-plan.md:14`,
`todos/workflow-engine-refactor/implementation-plan.md:19`,
`todos/workflow-engine-refactor/implementation-plan.md:557`).

Under the review-plan procedure, this is a requirement-coverage failure: the
approved requirements still demand behavior the plan no longer intends to
deliver. A reviewer cannot silently rewrite scope at plan-review time. Either
the requirements must be updated and re-reviewed to match the reduced scope, or
the plan must be expanded again to cover the still-approved requirements.

### C2: The proposed workflow schema cannot express the behaviors the rest of the plan requires

Task 2.1 defines a narrow schema: one producer `command`, one optional
`validator`, and no fields for alternate commands, thresholds, or pre-dispatch
behavior (`todos/workflow-engine-refactor/implementation-plan.md:179`,
`todos/workflow-engine-refactor/implementation-plan.md:189`).

Later tasks require metadata the schema does not model:

- bug-specific alternate build command and `pre_dispatch`
  (`todos/workflow-engine-refactor/implementation-plan.md:245`)
- DOR threshold metadata for the gate step
  (`todos/workflow-engine-refactor/implementation-plan.md:234`)
- a gates step that runs both `run_build_gates` and `verify_artifacts`
  (`todos/workflow-engine-refactor/implementation-plan.md:248`)
- a validator registry that claims to reference the current helper functions
  directly even though their signatures do not share the proposed protocol:
  `run_build_gates(worktree_cwd, slug)` and
  `verify_artifacts(worktree_cwd, slug, phase, *, is_bug=False)`
  (`teleclaude/core/next_machine/core.py:449`,
  `teleclaude/core/next_machine/core.py:680`)

As written, the builder would have to invent extra schema fields, wrappers, or
hard-coded exceptions during implementation. That means the plan is not
executable without guessing, which fails the plan-quality and grounding gates.

## Important

### I1: Final verification omits the required pre-commit-hook verification path

The approved requirements explicitly require hooks to pass
(`todos/workflow-engine-refactor/requirements.md:88`), the testing policy says
pre-commit hooks are the primary verification path, and the Definition of Done
requires hooks to pass and be verified. Task 5.2 only calls out `make test`,
`make lint`, and ad hoc checks
(`todos/workflow-engine-refactor/implementation-plan.md:512`).

Without an explicit hook-verification step, the builder can follow the plan and
still miss a mandatory repository gate.

## Suggestion

- None.
