# DOR Gate Report: mcp-migration-tc-cli

## Gate Verdict: needs_work → draft updated

**Previous score:** 4/10 (empty implementation plan)
**Draft assessment:** 7/10 (plan filled, requirements tightened)
**Assessed:** 2026-02-18

---

## What Changed in Draft

1. **Implementation plan filled in** — 4 phases, 12 tasks, specific files, method
   mapping table, pseudocode for RPC endpoint and CLI dispatch pattern.
2. **Requirements tightened** — clarified agent alias "unused" claim with evidence
   (grep confirmed no agent references), clarified `telec docs` needs no extension.
3. **Design decisions documented** — single `/rpc` endpoint, nested CLI dispatch,
   direct backend calls (not through MCP mixin).

## Remaining Concerns for Gate

### Gate 4: Approach known — NOW SATISFIED

The plan now covers:

- RPC endpoint design with method dispatch dict
- CLI subcommand registration (new enum values + group handlers)
- Full 24-tool method mapping table
- `caller_session_id` injection via HTTP header
- File-level breakdown (3 new files, 2 modified)

### Gate 8: Tooling impact — NOTED

The plan acknowledges that downstream todos handle tool spec updates and
CLAUDE.md baseline revision. Integration notes section added.

### Open Question (non-blocking)

`sessions.create` and `sessions.command` require listener registration for
AI-to-AI notifications. The plan notes this requires extracting the listener
logic from `MCPHandlersMixin._register_listener_if_present` into a shared
utility. This is additional work but straightforward — the logic is ~30 lines.

## Recommendation

Ready for re-gate. Expected score: 8+ with the filled plan and tightened
requirements.
