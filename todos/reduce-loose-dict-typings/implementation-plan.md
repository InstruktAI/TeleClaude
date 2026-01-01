# Implementation Plan: Reduce Loose Dict Typings

## Philosophy: Co-locate First, Extract Only When Shared

**Core principle:** Types live next to their primary usage. Only extract to shared location when 2+ modules need to import the same type.

**CRITICAL: Respect mypy overrides from pyproject.toml** - Some files/modules have intentional mypy relaxations for third-party boundaries. Don't waste time typing what mypy doesn't check.

## Type Ignore Comment Policy

**ALWAYS document WHY you're ignoring type errors.** Use this format:

```python
# type: ignore[error-code]  # Reason: explanation with GitHub issue if applicable
```

### When to Use Type Ignore Comments

| Scenario | Format | Example |
|----------|--------|---------|
| **MCP decorators** | `# type: ignore[untyped-decorator]  # MCP decorators use Callable[...] - see issue #1822` | `@server.call_tool()  # type: ignore[untyped-decorator]  # MCP decorators use Callable[...] - see issue #1822` |
| **Third-party untyped** | `# type: ignore[import-untyped]  # Library X has no type stubs` | Only if library truly has no stubs AND no `@types-*` package |
| **Known library bugs** | `# type: ignore[arg-type]  # Library Y bug: github.com/org/repo/issues/123` | Include upstream issue URL |

### When NOT to Use Type Ignore

**Never use `# type: ignore` for:**
- ❌ Our own code - fix the type error instead
- ❌ Missing type annotations - add them instead
- ❌ Complex types - simplify or use TypedDict/Protocol
- ❌ "It's too hard" - that means you need to understand the code better
- ❌ Broad ignores like `# type: ignore` without error code - ALWAYS specify the error code

### Error Codes Reference

Common error codes you might encounter:
- `untyped-decorator` - Decorator doesn't preserve types (MCP decorators)
- `import-untyped` - Third-party library has no type stubs
- `no-any-return` - Function returns Any (fix by typing the return)
- `arg-type` - Argument type mismatch (fix by correcting types)
- `assignment` - Assignment type mismatch (fix by correcting types)

**Rule:** If you find yourself using `# type: ignore`, first ask: "Can I fix this properly instead?"

## Current State Analysis

After investigating the codebase, here's what types exist and where they're used:

| Type Location | Types | Shared? | Action |
|--------------|-------|---------|--------|
| `command_handlers.py` | `SystemStats`, `MemoryStats`, `DiskStats`, `CpuStats` | ✅ Used in `models.py` | **Extract** to `teleclaude/types/system.py` |
| `telegram_adapter.py` | `HandleEventResult`, `HandleEventData` | ❌ Only used in telegram_adapter.py | **Keep** in place |
| `mcp_server.py` | MCP tool return types (~26 occurrences) | ❌ Only returned to MCP clients | **Define** as local TypedDicts |
| `daemon.py` | Deployment status payloads (~8 occurrences) | ❌ Only used in daemon.py | **Define** as local TypedDicts |
| `command_handlers.py` | Handler return types (~5 occurrences) | ⚠️ Returned to callers but not imported | **Define** as local TypedDicts |

**Total `dict[str, object]` count:** ~155 occurrences across 27 files
**Target reduction:** ~50% (from 155 → ~78)

## Group 1: Extract Truly Shared Types (SystemStats Family)

**Goal:** Create shared types module for system statistics used across modules.

**Files to create:**
- `teleclaude/types/__init__.py` - Package marker + re-exports
- `teleclaude/types/system.py` - SystemStats family

**Why package style?** Prepares for future shared types without requiring restructuring.

**Structure:**

```python
# teleclaude/types/system.py
from typing import TypedDict

class MemoryStats(TypedDict):
    """Memory statistics structure."""
    total_gb: float
    available_gb: float
    percent_used: float

class DiskStats(TypedDict):
    """Disk statistics structure."""
    total_gb: float
    free_gb: float
    percent_used: float

class CpuStats(TypedDict):
    """CPU statistics structure."""
    percent_used: float

class SystemStats(TypedDict):
    """System statistics structure."""
    memory: MemoryStats
    disk: DiskStats
    cpu: CpuStats
```

```python
# teleclaude/types/__init__.py
"""Shared type definitions for TeleClaude."""

from teleclaude.types.system import CpuStats, DiskStats, MemoryStats, SystemStats

__all__ = ["SystemStats", "MemoryStats", "DiskStats", "CpuStats"]
```

**Files to update:**
- [x] `teleclaude/core/command_handlers.py` - Remove definitions, import from types.system
- [x] `teleclaude/core/models.py` - Change `system_stats: dict[str, object] | None` → `SystemStats | None`, import from types

**Testing after Group 1:**
```bash
make lint   # Verify mypy passes, no circular imports
make test   # Verify runtime behavior unchanged
git commit -m "refactor(types): extract SystemStats family to shared types module"
```

## Group 2: Type MCP Server Returns (Co-located)

**Goal:** Replace `dict[str, object]` with local TypedDicts in `mcp_server.py`.

**Why co-locate?** These types are only used by MCP server - they're returned to external MCP clients but not imported by other teleclaude modules.

**Approach:**
1. Add TypedDict definitions at top of `mcp_server.py` (after imports, before class)
2. Update method return types from `dict[str, object]` → specific TypedDict
3. Ensure dict literals match TypedDict structure
4. Keep decorator `# type: ignore` with explanation (see Type Ignore Policy above)

**Example of proper type ignore usage:**
```python
# CORRECT - Specific error code + explanation
@server.call_tool()  # type: ignore[untyped-decorator]  # MCP decorators use Callable[...] - see issue #1822
async def call_tool(name: str, arguments: dict[str, object]) -> list[TextContent]:
    # Function body is fully typed ✅
    ...

# WRONG - No explanation
@server.call_tool()  # type: ignore
async def call_tool(name: str, arguments: dict[str, object]) -> list[TextContent]:
    ...
```

**Categories (~26 occurrences):**

**a) Computer/Peer info:**
```python
class ComputerInfo(TypedDict):
    """Computer information returned by list_computers."""
    name: str
    status: str
    last_seen: datetime
    adapter_type: str
    user: str | None
    host: str | None
    role: str | None
    system_stats: SystemStats | None  # Import from teleclaude.types
```

**b) Session info:**
```python
class SessionInfo(TypedDict):
    """Session information returned by list_sessions."""
    session_id: str
    origin_adapter: str
    title: str
    working_directory: str
    status: str
    created_at: str
    last_activity: str
    computer: str

class SessionDataResult(TypedDict):
    """Result from get_session_data."""
    session_id: str
    status: str
    transcript: str | None
    last_activity: str | None
    working_directory: str | None
```

**c) Command results:**
```python
class StartSessionResult(TypedDict):
    """Result from start_session."""
    session_id: str
    status: str
    message: str | None

class SendMessageResult(TypedDict):
    """Result from send_message."""
    status: str
    message: str | None

class RunAgentCommandResult(TypedDict):
    """Result from run_agent_command."""
    status: str
    session_id: str
    message: str | None
```

**d) Deployment results:**
```python
class DeployComputerResult(TypedDict):
    """Deployment result for a single computer."""
    status: str
    message: str | None

class DeployResult(TypedDict):
    """Result from deploy (all computers)."""
    # Key is computer name, value is per-computer result
    # This is dict[str, DeployComputerResult] but we return it as dict[str, dict[str, object]]
    # Keep as dict[str, dict[str, object]] for flexibility
```

**Testing after Group 2:**
```bash
make lint   # Verify mypy passes
make test   # Run MCP-related tests
git commit -m "refactor(mcp): add TypedDicts for MCP tool return values"
```

## Group 3: Type Command Handler Returns (Co-located)

**Goal:** Define TypedDicts for `command_handlers.py` function returns.

**Why co-locate?** These are part of command_handlers API. Even though mcp_server.py calls these functions, it doesn't import the types - it just receives the dicts.

**Types to define (~5 occurrences):**

```python
# Add to command_handlers.py after SystemStats (which will be removed)

class SessionListItem(TypedDict):
    """Session list item returned by handle_list_sessions."""
    session_id: str
    origin_adapter: str
    title: str
    working_directory: str
    status: str
    created_at: str
    last_activity: str

class ProjectInfo(TypedDict):
    """Project info returned by handle_list_projects."""
    name: str
    desc: str
    location: str

class ComputerInfoData(TypedDict):
    """Computer info returned by handle_get_computer_info."""
    user: str | None
    host: str | None
    role: str | None
    system_stats: SystemStats | None  # Import from teleclaude.types

class SessionDataPayload(TypedDict):
    """Session data payload returned by handle_get_session_data."""
    session_id: str
    status: str
    transcript: str | None
    last_activity: str | None
    working_directory: str | None

class EndSessionResult(TypedDict):
    """Result from handle_end_session."""
    status: str
    message: str
```

**Update signatures:**
- `handle_list_sessions() -> list[dict[str, object]]` → `list[SessionListItem]`
- `handle_list_projects() -> list[dict[str, str]]` → `list[ProjectInfo]`
- `handle_get_computer_info() -> dict[str, object]` → `ComputerInfoData`
- `handle_get_session_data(...) -> dict[str, object]` → `SessionDataPayload`
- `handle_end_session(...) -> dict[str, object]` → `EndSessionResult`

**Testing after Group 3:**
```bash
make lint
make test
git commit -m "refactor(handlers): add TypedDicts for command handler returns"
```

## Group 4: Type Daemon Deployment Payloads (Co-located)

**Goal:** Define TypedDicts for deployment status payloads in `daemon.py`.

**Why co-locate?** Only used within daemon's `handle_deploy` method. Not shared.

**Types to define (~8 occurrences):**

```python
# Add near top of daemon.py after imports

class DeployStatusPayload(TypedDict):
    """Base deployment status payload."""
    status: str
    timestamp: float

class DeployErrorPayload(TypedDict):
    """Deployment error payload with error details."""
    status: str  # Always "error"
    error: str

# Usage examples:
# deploying_payload: DeployStatusPayload = {"status": "deploying", "timestamp": time.time()}
# git_error_payload: DeployErrorPayload = {"status": "error", "error": f"git pull failed: {msg}"}
# restarting_payload: DeployStatusPayload = {"status": "restarting", "timestamp": time.time()}
```

**Update in `handle_deploy` method:**
- Replace `dict[str, object]` with `DeployStatusPayload` or `DeployErrorPayload`
- ~8 occurrences total

**Testing after Group 4:**
```bash
make lint
make test
git commit -m "refactor(daemon): add TypedDicts for deployment status payloads"
```

## Group 5: Type Telegram Adapter (Already Done)

**Status:** `HandleEventResult` and `HandleEventData` already defined as TypedDicts in `telegram_adapter.py`.

**Action:** ✅ No changes needed - already following co-location pattern.

## Keep Loose (Intentionally NOT Changed)

These files/patterns should keep `dict[str, object]` for valid reasons:

### Files with mypy overrides (from pyproject.toml)

| File/Module | Mypy Override | Why Keep Loose | Occurrences |
|------------|--------------|----------------|-------------|
| `teleclaude/hooks/*` | `ignore_errors = true` | **COMPLETELY IGNORED** - Agent hook adapters deal with untyped external responses | ~8 |
| `teleclaude/adapters/redis_adapter.py` | Major relaxations (`no-any-return`, `explicit-any`) | Redis client returns untyped data - third-party boundary | ~12 |
| `teleclaude/mcp_server.py` | Major relaxations (allows `explicit-any`) | MCP library decorators are untyped - third-party boundary. We CAN type our return values, but `arguments: dict[str, object]` stays loose. | ~31 total (~26 can be typed) |
| `teleclaude/core/command_handlers.py` | Some relaxations (`explicit-any` allowed) | Decorators cause typing issues - but we CAN type function returns | ~5 can be typed |
| `tests/*` | `disallow_untyped_defs = false` | Test data flexibility - acceptable | Various |

### Patterns that should stay generic

| Pattern | Why Keep Loose | Examples |
|---------|---------------|----------|
| External parsing | Unknown/dynamic structure from external sources | `teleclaude/utils/transcript.py` (JSONL parsing) |
| `raw` fields | Flexible schema for agent hook data | `teleclaude/core/events.py` - `raw` fields |
| `from_dict()` parameters | Input validation pattern - accepts any dict for validation | All dataclass `from_dict()` methods |
| `asdict()` returns | Serialization output - should be generic | All dataclass serialization |
| MCP tool `arguments` | External MCP client input - unknown structure | `call_tool(arguments: dict[str, object])` |
| Third-party callbacks | Untyped library callbacks and hooks | Various adapter integration points |

## Success Metrics

### Quantitative

**Baseline:** ~155 total `dict[str, object]` occurrences across 27 files

**Breakdown:**
- Can be typed: ~43 (SystemStats: 4, MCP: 26, Handlers: 5, Daemon: 8)
- Must keep loose: ~112 (hooks: 8, redis: 12, boundaries: ~92)

**Target reduction:** ~43 typed = ~28% reduction (from 155 → ~112)

**Note:** 50% reduction unrealistic - majority are intentional third-party boundaries or mypy-excluded modules.

### Qualitative

- [ ] All typeable occurrences converted to TypedDicts
- [ ] All new TypedDicts are co-located with their primary usage
- [ ] Only SystemStats extracted to shared location (truly shared type)
- [ ] Respect all mypy overrides - don't type what mypy ignores
- [ ] `make lint` passes with no new mypy errors
- [ ] `make test` passes with no runtime breakage
- [ ] No circular import warnings
- [ ] Code follows Python best practice: co-locate by default, extract only when shared

## Implementation Order Summary

1. ✅ **Group 1:** Extract SystemStats to `teleclaude/types/` (1 commit)
2. ✅ **Group 2:** Type MCP server returns in `mcp_server.py` (1 commit)
3. ✅ **Group 3:** Type command handler returns in `command_handlers.py` (1 commit)
4. ✅ **Group 4:** Type daemon deployment payloads in `daemon.py` (1 commit)

**Total:** 4 focused commits, each independently tested and validated.

---

## Why This Plan Is Smart

✅ **Follows Python best practices** - Co-locate types with their usage
✅ **Minimal abstraction** - Only one shared types module (for SystemStats)
✅ **Easy to navigate** - Types are where you expect them
✅ **No over-engineering** - No premature package structure
✅ **Clear ownership** - Each module owns its types
✅ **Scales well** - Can add more shared types to `teleclaude/types/` later
✅ **Testable** - Each group is independently verifiable
✅ **Maintainable** - Types change with the code that uses them
