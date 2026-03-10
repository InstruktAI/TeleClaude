---
id: 'software-development/policy/regression-zero-tolerance'
type: 'policy'
scope: 'global'
description: 'Regression is the supreme red flag. No change that introduces unscoped modifications may be merged, finalized, or approved under any circumstance.'
---

# Regression Zero Tolerance — Policy

## Rules

- **Regression blocks everything.** No review verdict, no state machine output, no process automation overrides this rule. If a branch contains changes outside the original task scope, it is contaminated and must not be merged.
- When code and tests disagree, builders must ascertain what is authoritative for the active objective and fix the stale side of the mismatch.
- Builders must not change runtime behavior solely because a pre-existing test is red, and must not rewrite a test solely because current code behaves differently.
- Builders must resolve the mismatch by determining what is leading in context: the active objective, the surrounding invariants, the traced behavior, and the strongest current evidence.
- **Scope is sacred.** A bug fix touches the bug. A feature touches the feature. Lint sweeps, formatting passes, type annotation cleanups, and "while I'm here" improvements are **not** part of the task unless explicitly requested. Any file changed that is not directly required by the task scope is a regression risk.
- **Builders must not expand scope.** When a builder encounters pre-existing lint errors, test failures, or code quality issues outside the task scope, they must document them (deferrals, bug reports) — not fix them in the same branch. The only changes permitted are those necessary to make the task's own code pass gates.
- Unrelated failures may be investigated and classified, but they must not pull the branch into unrelated behavior changes.
- **Reviewers must reject scope creep.** A review that approves a branch containing unscoped changes is a failed review, regardless of whether those changes are "improvements." The reviewer must flag every unscoped file as a blocker.
- **Orchestrators must verify scope before merge.** Before any finalize or merge action, the orchestrator must compare the branch diff against the original task scope. If files outside scope are modified, the orchestrator must block the merge — not delegate this judgment to reviews or state machines.
- **Machine verdicts do not override human judgment.** A review verdict of APPROVE, a state machine returning FINALIZE, or any automated signal does not authorize merging a branch that contains regression risk. The agent performing the merge is personally responsible for verifying scope.
- **When in doubt, do not merge.** If there is any uncertainty about whether a change is in scope, the default action is to block and escalate. The cost of a delayed merge is zero. The cost of merged regression is catastrophic.

## Rationale

- Regression is the single most destructive failure mode in software development. A working system that breaks because of an unrelated change destroys trust, wastes investigation time, and compounds downstream.
- Process automation (state machines, review verdicts, gate checks) exists to assist judgment, not replace it. An agent that merges regression because "the machine said APPROVE" has abdicated responsibility.
- Scope discipline is the primary defense against regression. Every unscoped change is an untested, unreviewed mutation that bypasses the quality contract of the original task.

## Scope

- Applies to all agents, all roles, all repositories, all tasks.
- Applies at every phase: build, review, fix, finalize, merge.
- Supersedes review verdicts, state machine outputs, and orchestration instructions when they conflict with regression safety.

## Enforcement

- Any agent that merges, approves, or advises merging a branch containing unscoped changes is in violation of this policy.
- Orchestrators must run a scope check (diff files vs. task requirements) before every finalize action.
- Builders that expand scope must have their changes reverted to the scoped subset before the branch can proceed.
- This policy has the highest priority of all software development policies. No other policy, procedure, or instruction may override it.

## Exceptions

- None. There are no exceptions to regression zero tolerance.
