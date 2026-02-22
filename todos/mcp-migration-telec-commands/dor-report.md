# DOR Report: mcp-migration-telec-commands

## Gate Verdict: PASS — Score 9/10

**Assessed:** 2026-02-22 (gate phase)

## Gate Analysis

### Gate 1: Intent & success — PASS

Problem statement clear: replace MCP tool invocation with telec CLI subcommands.
Success criteria are specific and testable (14 concrete checkboxes).

### Gate 2: Scope & size — PASS

3 new files, 2 modifications. All wiring — no new business logic. Volume is
high (24 subcommands, 14 new endpoints) but complexity per unit is low.

Split point identified if a single session can't handle it: API work (Phase 1-2)
separate from CLI work (Phase 3-4).

### Gate 3: Verification — PASS

Functional tests defined for each subcommand group. Error handling tests cover
daemon-down, invalid input, missing params. Regression tests ensure existing
commands unaffected.

### Gate 4: Approach known — PASS

Pattern is established in the codebase:

- REST routers: 5 existing separate routers (`channels/api_routes.py`,
  `memory/api_routes.py`, `hooks/api_routes.py`, `api/streaming.py`,
  `api/data_routes.py`) mounted via `include_router()`.
- CLI dispatch: `TelecCommand` enum + `_handle_cli_command()` pattern.
- Backend functions: same ones MCP handlers call.

**Correction applied:** Draft claimed 16 new endpoints; gate verified that
channels already has REST endpoints at `/api/channels/` (publish + list).
Corrected to 14 new endpoints; CLI channels subcommands wire to existing routes.

### Gate 5: Research — N/A

No new third-party dependencies. httpx (sync mode) already in use.

### Gate 6: Dependencies — PASS

No prerequisite todos. This is the MCP migration chain's starting point.
MCP server continues running in parallel — no ordering constraint.

### Gate 7: Integration safety — PASS

New endpoints under `/tools/` prefix — no collision with existing routes.
New `TelecCommand` enum values — no collision with existing commands (verified).
Agent aliases (`telec claude/gemini/codex`) confirmed unused by agent artifacts.
Incremental merge: new code is additive, removal is isolated.

### Gate 8: Tooling impact — PASS (with note)

Changes CLI surface (`telec --help`). The `telec-cli-surface` doc snippet and
`command-surface` spec still list `claude`, `gemini`, `codex` as commands.
These specs should be updated either in this todo or explicitly deferred to
Phase 6 (doc updates). The implementation plan already includes removing
enum values and CLI_SURFACE entries — the doc snippets are a small addition.

## Corrections Applied by Gate

1. **Endpoint count:** 16 → 14. Channels already served by `/api/channels/`.
2. **CLI mapping table:** Updated channels rows to reference existing endpoints.
3. **Task checklist:** Removed channels from new endpoint creation list.

## Assumptions (validated)

1. `telec context query` replaces `teleclaude__get_context` — the existing
   `telec docs` command is a different interface (human-oriented, no two-phase flow).
2. Sync httpx is sufficient for CLI tool calls — no streaming needed.
3. Agent alias removal (`telec claude/gemini/codex`) is safe — confirmed no
   agent artifacts reference these commands in `.py`, `.yaml`, `.yml`, or `.json`.

## Open Questions

None blocking.
