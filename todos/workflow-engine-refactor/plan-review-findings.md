# Plan Review Findings: workflow-engine-refactor

## Critical

### C1: The plan still fails DOR Gate 2 because it combines multiple independently shippable workstreams

The current plan bundles three distinct delivery streams into one builder
session:

- the core engine migration and equivalence harness across
  `teleclaude/core/next_machine/core.py`, the new engine module, validators,
  YAML workflow files, and the new tests
- the consolidated `/next-workflow` slash-command surface
- the language-baseline/config-surface work introduced in Task 2.3

Those streams are not a single indivisible behavior in the current codebase.
The engine migration can ship while continuing to emit the existing per-step
commands, and the command/config surface changes can follow without creating a
half-working codebase. With `core.py` already at 4200 lines and the plan adding
new runtime modules, workflow definitions, command artifacts, and tests, the
work exceeds one builder session and should be split into dependent todos
before implementation starts.

### C2: Task 2.3 introduces an ungrounded config surface and omits the required config-surface updates

Task 2.3 says the engine should read `teleclaude.yml` keys `language` or
`languages`, but the current config surface does not define those keys.
`docs/project/spec/teleclaude-config.md`, `config.sample.yml`, and the config
wizard surface cover `computer`, `agents`, `redis`, `whatsapp`, `deployment`,
`people`, and `jobs`, not project-language selection.

That creates two defects:

- the plan is not grounded in the current config spec
- the plan misses the mandatory review-lane work for a new config surface
  (wizard, sample config, and spec updates)

As written, the builder would have to invent a new config contract mid-build.
This must be resolved in planning first.

### C3: Task 5.1 is not grounded in the current slash-command/session-role architecture

Task 5.1 assumes one `/next-workflow` command can operate in both orchestrator
mode (`/next-workflow prepare`) and worker mode (`/next-workflow work build`).
The current command plumbing does not work that way:

- `teleclaude/core/command_service.py` assigns `system_role` and `job` from
  `COMMAND_ROLE_MAP`, keyed only by `SlashCommand`
- `teleclaude/api_server.py` derives session metadata from the slash command
  before arguments are interpreted

That means a single slash command cannot be both an orchestrator and a worker
without additional architecture the plan does not define. The task also omits
the required wiring files for slash-command integration, so the path is not
fully grounded against the existing command system.

## Important

- None.

## Suggestion

- None.

## Resolved During Review

- Tightened the dispatch-equivalence test wording in
  `implementation-plan.md` so verification asserts execution-significant fields
  instead of hardcoding human-facing orchestration prose, aligning the plan
  with the testing policy.
- Expanded `state.yaml` grounding metadata so the plan's referenced file set is
  tracked for staleness detection.
