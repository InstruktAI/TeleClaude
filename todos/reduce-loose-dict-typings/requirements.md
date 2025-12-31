# Requirements: Reduce Loose Dict Typings

## Problem Statement

The codebase has ~130 instances of `dict[str, object]` (and a few `dict[str, Any]`) spread across 25+ source files. These loose typings:

1. **Hide structure** - No IDE autocomplete or type checking for known fields
2. **Allow runtime errors** - Missing keys or wrong types discovered only at runtime
3. **Obscure intent** - Readers can't tell what shape the data should have

## Goals

### Must-Have

1. **Replace `dict[str, object]` with TypedDicts where structure is known**
   - Event dataclass fields (`raw`, `updated_fields`, `details`, `channel_metadata`)
   - MCP tool return types
   - Session/computer info structures
   - Configuration data structures

2. **Keep `dict[str, object]` only where truly dynamic**
   - External JSON parsing (transcript files, Redis messages from unknown agents)
   - Serialized dataclass output (`asdict()` returns)
   - JSON payloads passed through without inspection

3. **Maintain backward compatibility**
   - No breaking changes to MCP tool signatures
   - No changes to wire format (JSON serialization)

### Nice-to-Have

- Reduce boilerplate by using `TypedDict` inheritance for shared fields
- Consider `total=False` for optional fields instead of `Optional` wrappers

## Non-Goals

- Changing the `redis_adapter.py` - explicitly excluded from scope
- Introducing runtime validation (Pydantic, msgspec) - this is static typing only
- Refactoring dataclass hierarchies - only add TypedDicts for dict fields

## Constraints

1. **Python 3.11+ syntax** - Use `class FooDict(TypedDict)` not older `FooDict = TypedDict(...)`
2. **No new dependencies** - `typing` and `typing_extensions` only
3. **Incremental adoption** - Files can be updated independently
4. **Tests must pass** - All existing tests remain green

## Categories of Dict Usage

From analysis, loose dicts fall into these categories:

| Category | Example | Action |
|----------|---------|--------|
| Event raw payload | `AgentStart.raw` | TypedDict for known structure |
| MCP return type | `-> dict[str, object]` | TypedDict for tool responses |
| Session/computer info | `system_stats`, `channel_metadata` | TypedDict for structured data |
| Transcript parsing | `entry: dict[str, object]` | Keep loose - external format |
| JSON passthrough | `asdict()` return | Keep loose - serialization |

## File Priority (by occurrence count)

High priority (>10 occurrences):
- `mcp_server.py` (26)
- `utils/transcript.py` (23) - mostly keep loose
- `core/adapter_client.py` (14)
- `core/models.py` (12)

Medium priority (5-10):
- `daemon.py` (8)
- `core/events.py` (7)
- `core/agent_parsers.py` (7)
- `core/ux_state.py` (6)
- `core/command_handlers.py` (5)

Lower priority (<5):
- Remaining files with 1-4 occurrences

## Success Criteria

1. At least 50% reduction in `dict[str, object]` occurrences (targeting ~65 remaining)
2. `make lint` passes with no new warnings
3. `make test` passes
4. IDE autocomplete works for TypedDict fields in key paths
