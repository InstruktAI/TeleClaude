# Plan Review Findings: prepare-pipeline-hardening

## Critical

### C1: Task 7 contradicts R10 on where split children resume after an approved plan

`requirements.md` says a child created from a parent with an approved
`implementation-plan.md` starts at build, not another prepare phase. Task 7’s
verification instead hardcodes `prepare_phase=gate` for that case.

This is a direct requirement contradiction, not an implementation detail.
Approving the plan as written would deliver different split behavior from the
approved requirement.

### C2: R13’s `prepare.input_consumed` event has no implementation task

R13 requires emitting `prepare.input_consumed` when discovery consumes
`input.md`. The plan only mentions that event in Task 8’s schema registration
list. No task wires emission into `input_assessment`, `triangulation`, or any
shared helper, and no verification item proves the event is emitted.

Registering the schema alone does not satisfy the requirement’s event coverage
contract.

### C3: Task 9 does not cover the full documentation surface required by R15

R15 explicitly calls out the draft procedure, gate procedure, lifecycle state
machine documentation, and `telec todo split` help text in addition to the
review, discovery, prepare, CLI, and event docs. Task 9 updates only:

- `review-requirements`
- `review-plan`
- `next-prepare-discovery`
- `prepare`
- `event-vocabulary`
- `telec-cli-surface`

That leaves documented requirement coverage gaps before build starts.

## Important

### I1: The plan introduces `needs_decision` but does not update the supported verdict write path

Task 5 routes architectural findings through a new `NEEDS_DECISION` verdict.
The grounded code still validates prepare-review verdicts through
`_PREPARE_VERDICT_VALUES` and `/todos/mark-phase`, both of which accept only
`approve` and `needs_work`.

No task touches `mark_prepare_verdict`, `_PREPARE_VERDICT_VALUES`, or
`teleclaude/api/todo_routes.py`, so the supported prepare verdict API would
still reject the new value.

### I2: The plan does not include demo coverage for user-visible CLI and dispatch changes

Tasks 3, 5, 11, and 12 change operator-visible prepare output and add a new CLI
flag. The review-plan procedure requires demo coverage for user-facing changes,
and this todo already has a `demo.md` artifact, but no task updates or verifies
it.

Without a demo task, the plan is not anticipating the demo review lane the
builder will have to satisfy.
