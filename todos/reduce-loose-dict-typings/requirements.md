# Requirements: Reduce Loose Dict Typings

## Problem Statement

The codebase has ~130 instances of `dict[str, object]` spread across 25+ source files. These loose typings:

1. **Hide structure** - No IDE autocomplete or type checking for known fields
2. **Allow runtime errors** - Missing keys or wrong types discovered only at runtime
3. **Obscure intent** - Readers can't tell what shape the data should have

## Goals

### Must-Have

1. **Create centralized TypedDict module**
   - New file: `teleclaude/core/typed_dicts.py`
   - All TypedDict definitions in one discoverable location
   - Only depends on stdlib types (no circular imports)

2. **Consolidate existing TypedDicts**
   - Move `SystemStats`, `MemoryStats`, `DiskStats`, `CpuStats` from `command_handlers.py`
   - Move `HandleEventResult`, `HandleEventData` from `telegram_adapter.py`

3. **Add TypedDicts for MCP tool returns** (~26 occurrences in mcp_server.py)
   - `ComputerInfo` - list_computers return type
   - `SessionInfo` - list_sessions return type
   - `SessionDataResult` - get_session_data return type
   - `DeployResult` - deploy return type
   - Other tool-specific return types as needed

4. **Tighten dataclass fields in models.py** (~12 occurrences)
   - `PeerInfo.system_stats` → `SystemStats | None`
   - Other fields where structure is known

5. **Add TypedDicts for daemon.py deployment payloads** (~8 occurrences)
   - `DeployStatusPayload` for status updates

### Keep Loose (Intentionally)

- `teleclaude/utils/transcript.py` - Parsing arbitrary JSONL from external agents
- `teleclaude/adapters/redis_adapter.py` - Explicitly excluded from scope
- Event `raw` payloads in `events.py` - Agent hook data varies by agent
- `from_dict` method parameters - Input validation pattern
- `asdict()` returns - Serialization output

## Non-Goals

- Runtime validation (Pydantic, msgspec) - Static typing only
- Changing redis_adapter.py - Excluded from scope
- 100% coverage - Focus on high-impact files first

## Constraints

1. **Python 3.11+ syntax** - Use `class FooDict(TypedDict)` style
2. **No new dependencies** - `typing` and `typing_extensions` only
3. **No circular imports** - `typed_dicts.py` must be import-safe
4. **Tests must pass** - All existing tests remain green
5. **Lint must pass** - `make lint` with mypy strict mode

## Success Criteria

1. At least 50% reduction in `dict[str, object]` occurrences (from ~130 to ~65)
2. `make lint` passes with no new warnings
3. `make test` passes
4. IDE autocomplete works for TypedDict fields in key paths

## Implementation Priority

1. **Primary** (highest impact):
   - `mcp_server.py` (26 occurrences)
   - `models.py` (12 occurrences)

2. **Secondary**:
   - `daemon.py` (8 occurrences)
   - `command_handlers.py` (5 occurrences)

3. **Later/Optional**:
   - Remaining files with 1-4 occurrences
