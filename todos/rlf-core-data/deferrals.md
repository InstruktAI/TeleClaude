# Deferrals: rlf-core-data

## Deferral 1: Pre-existing lint violations outside scope

**Requirement:** `make lint` passes (ruff, pyright, mypy, pylint)

**Status:** Partial — ruff, pyright, mypy all pass for the 3 target packages.
The `make lint` guardrail step fails on 18 modules (all outside task scope).

**Evidence:** Before this task, the guardrail reported 21 violations including
`db.py` (2599), `command_handlers.py` (2031), and `models.py` (1112).
After this task, those 3 are gone. Remaining 18 are pre-existing:
`api_server.py`, `daemon.py`, `redis_transport.py`, `tmux_bridge.py`,
`agent_coordinator.py`, `transcript.py`, `telec.py`, `tool_commands.py`,
`ui_adapter.py`, `discord_adapter.py`, `telegram_adapter.py`,
`checkpoint.py`, `receiver.py`, `youtube_helper.py`, `next_machine/core.py`,
`integration/state_machine.py`, `resource_validation.py`, `adapter_client.py`.

**Why deferred:** Out of scope — requirements explicitly exclude changes to files
outside the 3 target modules.

**Resolution:** A separate todo should decompose each remaining large module.

**Outcome:** NOOP — existing roadmap todos (`rlf-cli`, `rlf-core-infra`, `rlf-adapters`, `rlf-core-machines`, `rlf-peripherals`, `rlf-services`, `rlf-tui`) already target these exact modules. Lint violations will be resolved as a natural byproduct of those decompositions.

---

## Deferral 2: Pylint import-outside-toplevel in command_handlers

**Requirement:** `make lint` passes pylint (with `fail-on = [import-outside-toplevel]`)

**Status:** Pre-existing violations. The original `command_handlers.py` contained
deferred imports (circular import avoidance) that were always C0415 violations.
Pylint was never reached via `make lint` because the guardrail blocked it first.

**Affected imports (carried from original):**
- `teleclaude.core.session_listeners.register_listener`
- `teleclaude.core.roadmap.assemble_roadmap`
- `teleclaude.core.inbound_queue.get_inbound_queue_manager`
- `teleclaude.core.command_handlers._keys.get_agent_command` (deferred in _keys.py)

**Why deferred:** These are circular-import avoidances from the original code.
Restructuring the circular imports is a separate architectural task.

**Resolution:** Fix circular imports in the listed modules to allow top-level imports,
or accept with explicit `# pylint: disable=import-outside-toplevel` comments.

**Outcome:** NEW_TODO — created `rlf-core-data-pylint` (after: rlf-core-data). Scoped to fixing or suppressing these 4 specific C0415 violations in the decomposed command_handlers package.
