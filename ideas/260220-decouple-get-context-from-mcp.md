# Decouple get_context from MCP Dependency

**Critical fragility:** Memory ID 40 identifies that `get_context` is the most essential tool for agents, but it depends on MCP, which depends on the daemon being up. When the daemon is down, we lose our knowledge entrypoint entirely.

**Current architecture:**

```
get_context → MCP client → MCP server → daemon
```

When daemon is down: no MCP → no get_context → agent is blind

**Impact:** This is a single point of failure. The most frequently-needed tool (context retrieval) is unavailable precisely when the daemon is down and needs debugging.

**Actionable insight:** Decouple get_context from MCP by implementing a fallback mode that:

1. **Phase 1: Direct filesystem read** - get_context should be able to read from the local doc index (`~/.teleclaude/docs/`) directly, without daemon intermediation
   - Build a minimal local index parser
   - Cache selected snippet IDs in a local manifest
   - Allow agents to call `get_context --offline` to read from local filesystem

2. **Phase 2: Hybrid behavior** - In normal operation, use MCP (gets daemon-managed caching). When MCP unavailable, fall back to filesystem read automatically.

**Benefit:** Agents can always retrieve context, even when debugging daemon issues. The knowledge entrypoint never goes dark.

**Next step:** Create `docs/architecture/get-context-resilience.md` with:

- Current dependency chain
- Proposed decoupling architecture
- Fallback behavior spec
- Implementation plan for Phase 1 (offline mode)
