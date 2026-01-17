# Input: deferral-automation

## Scope
- Deferral handling must be automated and deterministic.
- Orchestrator remains a thin executor of `next_machine` output.

## Desired Direction (Priority Order)
1. **Next-build first**: builders create `deferrals.md` only when strictly necessary, using a precise schema.
2. **Next-machine second**: detect `deferrals.md` and emit a single instruction to run `next-defer`.
3. **Next-defer**: runs in isolation and outputs either a new todo or nothing.
4. **Prime-administrator**: holds process-management guidance, separate from the orchestrator.
5. **Orchestrator stays thin**: no deferral decision tree; executes deterministic scripts only.

## Flow Model (Stateless)
- Each command executes in isolation.
- Orchestrator only dispatches deterministic scripts.
- `next-defer` consumes deferrals and writes outcomes (new todo or no-op).
