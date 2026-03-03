# DOR Report: cli-knowledge-commands

## Assessment: Draft

### Gate 1: Intent & Success — PASS

Requirements are explicit: consolidate three standalone tool specs into two `telec` CLI
subcommands (`history`, `memories`), then retire the specs. Problem statement, scope,
and 14 testable success criteria are defined.

### Gate 2: Scope & Size — PASS

Single-session scope. Changes are localized to:
- `telec.py` (enum + CLI_SURFACE + handlers)
- `api_client.py` (4 memory methods)
- 3 spec files to delete + 1 baseline file to edit
- Test file(s)

No cross-cutting changes. No multi-phase dependencies.

### Gate 3: Verification — PASS

Success criteria are concrete CLI invocations with observable output.
Error paths identified: daemon down for memories, missing args, invalid type.
Demo plan covers the full round-trip.

### Gate 4: Approach Known — PASS

The `CommandDef` + `_handle_*` dispatch pattern is well-established in `telec.py` with
15+ existing commands following the exact same structure. History wraps existing
`history.py` functions by import. Memories wraps existing daemon API via `TelecAPIClient`.
No novel patterns needed.

### Gate 5: Research Complete — PASS (auto-satisfied)

No new third-party dependencies. All functionality wraps existing internal modules.

### Gate 6: Dependencies & Preconditions — PASS

No blocking dependencies. `history-search-upgrade` is independent — when it lands,
`telec history` automatically benefits. No new config keys or env vars needed.

### Gate 7: Integration Safety — PASS

Additive change to the CLI surface. No existing behavior modified. Tool spec removal is
safe because the CLI commands fully replace them. Incremental merge is clean.

### Gate 8: Tooling Impact — PASS (auto-satisfied)

No scaffolding or tooling changes. `CLI_SURFACE` auto-generates the `telec-cli` spec.

## Assumptions

- `history.py` functions (`display_combined_history`, `show_transcript`, `_parse_agents`)
  are importable from the script path. If the module layout changes before build,
  the import path in the handler needs adjustment.
- The memory API routes (`/api/memory/search`, `/api/memory/save`, etc.) are stable
  and match the signatures documented in `api_routes.py`.

## Open Questions

None. All gates satisfiable from evidence.
