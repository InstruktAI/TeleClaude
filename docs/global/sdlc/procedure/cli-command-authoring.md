---
description: 'Procedure for adding new CLI commands to telec: REST model, surface registration, handler, API endpoint, tests.'
activation_trigger: Use when adding or changing a telec CLI command — a new subcommand, a new resource, or a change to an existing command's surface.
visibility: 'public'
---

# CLI Command Authoring — Procedure

## Goal

Add new CLI commands to `telec` consistently, following REST resource conventions and the established handler/surface/API pattern.

## Steps

1. **Define the REST resource model.** Use nouns with action subcommands: `artifacts {list|read|write}`, not verbs like `read-artifact`. Group related actions under a parent.

2. **Register in `CLI_SURFACE`.** Add a `CommandDef` entry in `teleclaude/cli/telec/surface.py` with description, args, flags, auth, and examples. This is the canonical surface definition. Every option is a named `Flag` constant declared in `teleclaude/cli/telec/flags.py` and referenced from the `CommandDef`, never an inline literal; an option shared by several commands is one constant reused by each. Every `Flag` declares its arity — presence-only, single value, repeated value, or a greedy run of values — because recognition derives from the declaration and an undeclared arity is a type error. **The `args` field must list every parameter on the usage line** — required positionals as `<name>`, optional positionals as `[<name>]`, and every optional flag as `[--flag <value>]` (or `[--flag]` for booleans). Agent artifacts render only this first line; flags listed only in the `flags` array are invisible in `telec -h` and AGENTS.md output. **`Flag(..., hidden=True)`** suppresses the flag from every overview surface — top usage args line, inline trailing summary, and the Flags/Options bullet list — across both `telec -h` (at every level) and the AGENTS.md surface build. The parser still accepts the flag and completion still suggests it; only the discoverability surface is suppressed. Use `hidden=True` for flags whose default is "do not use unless explicitly instructed" (current example: `--detach`), and put the rationale + sanctioned use case in the `notes` so an operator who legitimately needs the flag still finds the explanation. A command whose positional operand is free text that may begin with a dash declares the literal free-text option policy on its `CommandDef`; every other command is strict and rejects an undeclared option.

3. **Write the handler.** Add a function in the appropriate `teleclaude/cli/telec/handlers/` module. The handler obtains its `CommandDef` from the surface, hands argv to the shared declaration-driven parser in `teleclaude/cli/telec/handlers/_arg_parsing.py`, and reads options back through the same `Flag` constants the `CommandDef` declares. A handler never compares an argv token to a literal option string, never re-implements unknown-option or missing-value handling, and never prints its own usage on a parse error — the parser raises the usage error and the CLI entry point renders it. Handlers validate operand count and meaning, call the daemon API via `tool_api_request()`, and print output. Handlers are sync.

4. **Add the API endpoint** (if daemon-backed). Add a route in `teleclaude/api/` (e.g., `todo_routes.py`). Use FastAPI path/body params. Return `{"status": "ok", ...}` on success.

5. **Route the subcommand.** Wire the handler into the dispatcher function (`_handle_todo`, etc.) with the appropriate subcommand string match.

6. **Update `__all__` exports.** Add the handler to the module's `__all__` list.

7. **Bind functional tests to the command's feature-spec scenarios.** Where the command exposes observable product behavior, bind tests via `@spec` to the scenarios in its feature spec, exercising the real API integration at the handler boundary with real DB fixtures, not mock theater. A command that is pure contract tooling (a thin wrapper, a fixed-response shim) is not tested — the artifact is the spec.

8. **Evaluate `@exec` expansion.** Only add to `telec-cli.md` tool spec with 100% certainty of global need. Most commands do not need `@exec`.

9. **Add to `Required tools`** in relevant lifecycle procedure docs if the command is procedure-scoped.

10. **Verify.** `make restart && make status` for daemon-backed commands. Smoke test the full flow.

## Preconditions

- The daemon is running (`make status` returns HEALTHY) for daemon-backed commands.
- The developer has identified the REST resource model for the new command.

## Outputs

- A registered `CommandDef` in `CLI_SURFACE`.
- A handler function in `teleclaude/cli/telec/handlers/`.
- An API endpoint (if daemon-backed) in `teleclaude/api/`.
- Functional tests bound to the command's feature-spec scenarios (when it exposes observable behavior; contract tooling is not tested).

## Recovery

- If the handler fails at runtime, `ToolAPIError` is caught at the CLI entry point (`teleclaude/cli/telec/__init__.py`). Handlers never catch API errors — they propagate naturally.
- All API responses return `{"status": "ok", ...}` on success. Errors propagate as HTTP status codes with a `detail` field.
- CLI handlers are sync. For direct DB access (no daemon), use `asyncio.run()` with full async init/close, or sync `TodosDb` methods (`read_state_sync`, `write_state_sync`, `deliver_sync`). Prefer daemon API calls over direct DB access.
