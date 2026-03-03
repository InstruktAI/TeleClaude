# DOR Report: cli-knowledge-commands

## Assessment: Gate — needs_work

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

### Gate 4: Approach Known — NEEDS WORK

The `CommandDef` + `_handle_*` dispatch pattern is well-established. The memories
subcommand via `TelecAPIClient` is clean — confirmed API routes at
`/api/memory/save`, `/api/memory/search`, `/api/memory/timeline`,
`/api/memory/{id}` (DELETE).

**Blocker: history import mechanism.** The plan prescribes "Import `history.py`
functions: `display_combined_history`, `_parse_agents`" but `scripts/history.py` is
a standalone script, not a Python package module. Its core functions
(`scan_agent_history`, `find_transcript`, `_discover_transcripts`,
`_extract_session_id`, `_parse_agents`, `display_combined_history`,
`show_transcript`) are defined only in `scripts/history.py` and are not part of the
`teleclaude` package. The script uses `sys.path.insert(0, _REPO_ROOT)` to import
from `teleclaude` — the reverse direction (teleclaude importing from scripts/) is
not supported and would be fragile.

The plan and requirements both say "import and call, don't shell out" but neither
addresses the structural gap. The builder will hit this immediately.

**Required fix:** The implementation plan must prescribe one of:
1. Extract reusable functions from `scripts/history.py` into a proper module
   (e.g., `teleclaude/history/search.py`), then have both `scripts/history.py`
   and `telec.py` import from it.
2. Reimplement the ~60 lines of scanning/display logic directly in `telec.py`
   using the same underlying `teleclaude.utils.transcript` functions that
   `history.py` uses.

Option 1 is preferred — it keeps `scripts/history.py` as a thin CLI wrapper
and makes the logic properly reusable.

### Gate 5: Research Complete — PASS (auto-satisfied)

No new third-party dependencies. All functionality wraps existing internal modules.

### Gate 6: Dependencies & Preconditions — PASS

No blocking dependencies. `history-search-upgrade` is independent — when it lands,
`telec history` automatically benefits. No new config keys or env vars needed.

### Gate 7: Integration Safety — PASS

Additive change to the CLI surface. No existing behavior modified. Tool spec removal
is safe because the CLI commands fully replace them. Incremental merge is clean.

### Gate 8: Tooling Impact — PASS (auto-satisfied)

No scaffolding or tooling changes. `CLI_SURFACE` auto-generates the `telec-cli` spec.

## Plan-to-Requirement Fidelity

- Requirements say `telec memories timeline <id> [--before N] [--after N]`.
  Plan adds `--project` to timeline. The API supports it (`project: str | None`).
  Acceptable additive scope — not a contradiction.
- Memory API route params verified: `save` takes `text`, `title`, `type`, `project`,
  `concepts`, `facts`, `identity_key`. `search` takes `query`, `limit`, `project`,
  `type`, `identity_key`. `timeline` takes `anchor`, `depth_before`, `depth_after`,
  `project`. All match plan claims.
- The `--before`/`--after` CLI flags map to `depth_before`/`depth_after` API params.
  Naming translation is clear.

## Gate Verdict

| Gate | Result |
|------|--------|
| 1. Intent & Success | PASS |
| 2. Scope & Size | PASS |
| 3. Verification | PASS |
| 4. Approach Known | NEEDS WORK |
| 5. Research Complete | PASS |
| 6. Dependencies | PASS |
| 7. Integration Safety | PASS |
| 8. Tooling Impact | PASS |

**Score: 7/10** — One concrete blocker on the history import mechanism.
**Status: needs_work** — Fix the implementation plan to address the
`scripts/history.py` import gap before this is builder-ready.

## Actions Taken

- Verified `TelecCommand` enum and `CLI_SURFACE` pattern in `telec.py`.
- Verified memory API routes in `teleclaude/memory/api_routes.py` (save, search, timeline, delete).
- Verified `TelecAPIClient` has no existing memory methods (Task 1.4 is needed).
- Verified `history.py` function signatures (`display_combined_history`, `show_transcript`, `_parse_agents`).
- Confirmed `history.py` core functions (`scan_agent_history`, `find_transcript`) exist only in `scripts/`, not in `teleclaude/` package.
- Verified tool spec files exist at expected paths for retirement.
- Verified `docs/global/baseline.md` references at lines 6-8.
