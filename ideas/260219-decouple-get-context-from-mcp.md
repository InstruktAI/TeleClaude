# Decouple get_context from MCP dependency

## Problem

`get_context` is the most critical tool for agent knowledge discovery, but it depends on the daemon's MCP server. When the daemon is down (common during development, restarts, or incidents), agents lose their knowledge entrypoint entirely. This creates cascading failures: without get_context, agents make wrong decisions, miss context, and compound problems.

Memory #40 and #25 show this is recurring friction during maintenance windows and restarts.

## Opportunity

Split get_context into two paths:

1. **Online path:** MCP call to the live daemon (current behavior, best results)
2. **Offline path:** Read doc snippet index files directly from the filesystem

The offline path would:

- Read the doc snippet index from `docs/` directory (already in git)
- Provide partial but functional context even when daemon is down
- Restore agent autonomy during maintenance

## Scope

- Create offline doc discovery mechanism (direct filesystem walk)
- Keep MCP path as primary (higher quality, live data)
- Fallback gracefully from MCP to filesystem if daemon unavailable
- Test both paths

## Success criteria

- Agents can call get_context and get useful results even when daemon is offline
- Online and offline paths return consistent results (no contradictions)
- No performance regression on online path
