# Plan Review Findings: workflow-engine-refactor

## Critical

### C1: Task 2.3 sends the builder to the wrong config model file

Task 2.3 says to add the new `language` field to
`teleclaude/config/__init__.py`
(`todos/workflow-engine-refactor/implementation-plan.md:344-347`).

The project-level config model actually lives in `teleclaude/config/schema.py`
(`ProjectConfig` at `teleclaude/config/schema.py:250-260`), and
`teleclaude/config/loader.py` loads that model for `teleclaude.yml`
(`teleclaude/config/loader.py:8-9`, `teleclaude/config/loader.py:57-60`).
`teleclaude/config/__init__.py` is the runtime config module, not the
Pydantic project-config schema. As written, the builder would have to discover
and correct the file target mid-build, which fails the grounding gate.

### C2: The language-baseline design relies on a dispatch field the current command surface does not expose

Task 2.3 and Task 3.2 say `load_language_baseline()` should return extra
required-read content and that `emit_dispatch()` should merge it into the
dispatch instruction's `required_reads`
(`todos/workflow-engine-refactor/implementation-plan.md:351-357`,
`todos/workflow-engine-refactor/implementation-plan.md:465-467`).

The current dispatch contract has nowhere to carry that. `format_tool_call()`
only accepts `command`, `args`, `project`, `guidance`, `subfolder`, `note`,
`next_call`, `completion_args`, and `pre_dispatch`
(`teleclaude/core/next_machine/core.py:285-295`), and `telec sessions run`
accepts the same limited metadata
(`teleclaude/cli/tool_commands.py:342-398`). Worker required reads are declared
statically in the command artifacts themselves
(`agents/commands/next-build.md:10-16`). Without additional command-pipeline
work that the plan never names, this step is not implementable as written.

### C3: The work-machine equivalence plan drops the pre-build merge gate and its failure path

Current `next_work()` always merges `origin/main` into the worktree before any
build dispatch and returns `MERGE_MAIN_FAILED` if that merge step fails
(`teleclaude/core/next_machine/core.py:4033-4039`).

The work-step resolution and migration tasks cover state repair, stale approval,
bug routing, pre-dispatch, validators, finalize, and deferrals
(`todos/workflow-engine-refactor/implementation-plan.md:404-426`,
`todos/workflow-engine-refactor/implementation-plan.md:575-600`), but they
never mention `_merge_origin_main_into_worktree()` or the
`MERGE_MAIN_FAILED` response. Task 1.2's characterization suite also omits this
reachable behavior
(`todos/workflow-engine-refactor/implementation-plan.md:133-168`). Because
behavioral equivalence is the acceptance criterion, the missing merge gate is a
requirement-coverage failure.

## Important

### I1: The new `teleclaude.yml:language` surface is not carried through the repo's actual project-config touchpoints

The plan introduces a new top-level `language` key
(`todos/workflow-engine-refactor/implementation-plan.md:344-350`) and says
`telec init` can set it during onboarding
(`todos/workflow-engine-refactor/implementation-plan.md:327-328`), but the task
list only updates the repo's `teleclaude.yml` and the config spec.

The repo's existing project-config touchpoints include the `telec init` flow
that reads and rewrites `teleclaude.yml`
(`teleclaude/project_setup/init_flow.py:56-70`), the minimal project bootstrap
that creates `teleclaude.yml`
(`teleclaude/docs_index.py:399-407`), and the checked-in sample file
(`teleclaude.sample.yml:1-14`). None of those surfaces are included in the
plan, so the new config key is only partially surfaced and will trigger the
documentation/config review lane.

## Suggestion

- None.
