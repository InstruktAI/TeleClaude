# Requirements

- Refactor all Python files currently over 1,000 lines into smaller modules (target <800 lines where practical) without changing runtime behavior.
- Work must be parallelizable: each file’s refactor should be executable independently by separate subagents.
- Produce a minimal coordination layer that prevents cross‑file conflicts (imports and shared helpers only).
- Keep MCP/REST lifecycle ownership intact (no behavior changes to the lifecycle manager).
