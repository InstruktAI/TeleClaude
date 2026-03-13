# Input: rlf-core-data-pylint

## Context

The `rlf-core-data` refactor decomposed `teleclaude/core/command_handlers.py` into a package.
The original file used deferred (non-top-level) imports to avoid circular dependencies.
These were carried over into the new package structure and remain as pylint C0415 violations.

Pylint was never exercised during `rlf-core-data` because the `make lint` guardrail blocked
on the 18 remaining large-file violations first. Once those are addressed by subsequent `rlf-*`
todos, pylint will run and fail on these 4 imports.

## Affected locations

All in `teleclaude/core/command_handlers/`:

1. `register_listener` imported from `teleclaude.core.session_listeners` — deferred to avoid circular dep
2. `assemble_roadmap` imported from `teleclaude.core.roadmap` — deferred to avoid circular dep
3. `get_inbound_queue_manager` imported from `teleclaude.core.inbound_queue` — deferred to avoid circular dep
4. `get_agent_command` imported from `teleclaude.core.command_handlers._keys` — deferred to avoid circular dep

## Desired outcome

One of:
- Fix the circular import structure to allow top-level imports (preferred if low-risk)
- Add explicit `# pylint: disable=import-outside-toplevel` with an inline comment explaining
  the circular dep, for any that cannot be safely moved to top-level

`make lint` should pass without guardrail failures on these modules.
