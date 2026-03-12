# Bug: Integrator spawn fails with 400 (broken integration bridge)

## Symptom

`integration_bridge.spawn_integrator_session` fails with an HTTP 400 error when
the daemon attempts to spawn the integrator.  The error originates inside
`telec sessions run`, which requires a caller session identity
(`X-Caller-Session-Id` header) that the daemon process does not possess.

## Investigation

The call chain was:

1. A finalizer emits a FINALIZE_READY signal.
2. `integration_bridge.spawn_integrator_session` runs `_spawn_integrator_sync`
   in a thread via `asyncio.to_thread`.
3. `_spawn_integrator_sync` shells out to `subprocess.run(["telec", "sessions",
   "run", "--command", "/next-integrate", ...])`.
4. The `telec` CLI calls `POST /sessions/run` on the daemon API.
5. The `run_session` handler checks `if not identity.session_id` and raises
   `HTTP 400 — sessions/run requires caller session identity`.

The daemon has no tmux session identity to pass as `X-Caller-Session-Id`.
Shelling out to the CLI is fundamentally wrong here — the daemon is calling
itself as if it were an external client.

Secondary issues found during investigation:
- `session_metadata` flowed as an untyped `dict[str, object]` throughout the
  internal stack, bypassing type safety at DB, auth, and DTO boundaries.
- Raw command strings (`"next-build"`, `"next-integrate"`, …) were scattered
  across `api_server.py`, `next_machine/core.py`, and `preparation.py` instead
  of using an enum constant.
- `COMMAND_ROLE_MAP` lived in `api_server.py` but was also needed by
  daemon-internal spawning code, creating a coupling problem.
- `api/auth.py` used `isinstance(metadata, dict)` guard + `.get()` which would
  never match once `session_metadata` became a typed dataclass.

## Root Cause

`integration_bridge.py` attempted to spawn the integrator by invoking the
public CLI (`telec sessions run`), which requires a caller session identity that
the daemon itself cannot provide.  The session spawning API was never intended
to be callable without an authenticated session context.

## Fix Applied

**`teleclaude/constants.py`** — Added `SlashCommand(str, Enum)` and
`JobRole(str, Enum)` as canonical enumerations for slash commands and job roles.

**`teleclaude/core/models.py`** — Added `SessionMetadata` frozen dataclass
(`system_role`, `job`). Updated `MessageMetadata`, `Session`, and
`SessionSnapshot` to use `SessionMetadata | None` instead of
`dict[str, object] | None`. Updated all `to_dict()` / `from_dict()` methods
with proper serialization via `dataclasses.asdict()`.

**`teleclaude/types/commands.py`** — Typed `CreateSessionCommand.session_metadata`
as `SessionMetadata | None`.

**`teleclaude/core/db.py`** — Updated `_serialize_session_metadata` to accept
`SessionMetadata | None` and serialize via `dataclasses.asdict()`.  Updated
`_to_core_session` to deserialize JSON into `SessionMetadata`.

**`teleclaude/core/command_handlers.py`** — Removed coercion of
`cmd.session_metadata` to `{}`.  Pass `SessionMetadata | None` directly.

**`teleclaude/core/command_service.py`** — Moved `COMMAND_ROLE_MAP` here
(keyed by `SlashCommand`). Added `run_slash_command()` method for
daemon-internal session spawning that calls `create_session` directly without
needing a caller session identity.

**`teleclaude/api_server.py`** — Imported `COMMAND_ROLE_MAP` and `SlashCommand`
from canonical sources. Updated `WORKER_LIFECYCLE_COMMANDS` to use
`SlashCommand` members. Removed duplicate `COMMAND_ROLE_MAP` definition.
Fixed job filter to use attribute access (`s.session_metadata.job`). Updated
`run_session` handler to construct `SessionMetadata` and use `SlashCommand`.
Updated `create_session` handler to convert incoming dict to `SessionMetadata`.

**`teleclaude/api/auth.py`** — Replaced `isinstance(metadata, dict)` guard and
`.get("system_role")` with direct attribute access on `SessionMetadata`.

**`teleclaude/api_models.py`** — Added `dataclasses.asdict()` serialization of
`SessionMetadata` in `SessionDTO.from_core()` for the API response boundary.

**`teleclaude/core/agent_coordinator.py`** — Removed `isinstance(Mapping)`
guard; replaced with `metadata: dict[str, object] = {}` (actor name fields
were never in `SessionMetadata` — the lookup falls through to `ui_meta`).

**`teleclaude/core/next_machine/core.py`** — Replaced 15+ raw command strings
with `SlashCommand` enum members.

**`teleclaude/cli/tui/views/preparation.py`** — Replaced `"next-prepare"` and
`"next-work"` raw strings with `SlashCommand.NEXT_PREPARE` and
`SlashCommand.NEXT_WORK`.

**`teleclaude/core/integration_bridge.py`** — THE CORE FIX. Replaced the
`_spawn_integrator_sync` / `asyncio.to_thread` / `subprocess.run(["telec", ...])`
pattern with a direct async call to
`get_command_service().run_slash_command(SlashCommand.NEXT_INTEGRATE, ...)`.
The guard check now queries `db.list_sessions()` directly instead of shelling
out to `telec sessions list`. Removed `import subprocess`, `import json`,
`asyncio.to_thread`, `_spawn_integrator_sync`, and the dead
`TELECLAUDE_INTEGRATOR_PARITY_EVIDENCE` env var.
