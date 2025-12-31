# Implementation Plan: Reduce Loose Dict Typings

## Overview

Replace `dict[str, object]` with TypedDicts across the codebase, focusing on high-impact files first. Create a centralized `typed_dicts.py` module for all type definitions.

## Group 1a: Create TypedDict Catalog

**Goal:** Define all TypedDicts upfront in a single, import-safe module.

**Files to create:**
- `teleclaude/core/typed_dicts.py`

**Types to define:**

```python
# Existing (move from other files)
SystemStats, MemoryStats, DiskStats, CpuStats  # from command_handlers.py
HandleEventResult, HandleEventData  # from telegram_adapter.py

# MCP tool returns
ComputerInfo  # list_computers item
SessionInfo  # list_sessions item
SessionDataResult  # get_session_data return
StartSessionResult  # start_session return
SendMessageResult  # send_message return
DeployResult  # deploy return (per-computer)
DeployAllResult  # deploy return (all computers)

# Daemon payloads
DeployStatusPayload  # deployment status updates

# Models support
SystemStatsDict  # for PeerInfo.system_stats
```

**Constraints:**
- Only import from `typing`, `typing_extensions`, stdlib
- No imports from teleclaude modules (prevents circular imports)

## Group 1b: Update Imports

**Goal:** Point existing code to new TypedDict locations.

**Files to update:**
- [ ] `teleclaude/core/command_handlers.py` - Remove type definitions, import from typed_dicts
- [ ] `teleclaude/adapters/telegram_adapter.py` - Remove type definitions, import from typed_dicts

## Group 2: Models

**Goal:** Tighten dataclass field types using TypedDicts.

**Files to update:**
- [ ] `teleclaude/core/models.py`

**Changes:**
- `PeerInfo.system_stats: dict[str, object] | None` → `SystemStatsDict | None`
- Other fields where structure is known

**Why before MCP Server:** Smaller file, validates TypedDict imports work without issues.

## Group 3: MCP Server

**Goal:** Type all MCP tool return values.

**Files to update:**
- [ ] `teleclaude/mcp_server.py`

**Approach:**
1. Identify common patterns (session results, list items, status payloads)
2. Update method return types: `dict[str, object]` → specific TypedDict
3. Update internal dict literals to match TypedDict structure

**Categories (~26 occurrences):**
- Tool return types (majority)
- Internal helper returns
- Peer/computer info structures

## Group 4: Secondary Cleanup

**Goal:** Clean up remaining high-value occurrences.

**Files to update:**
- [ ] `teleclaude/daemon.py` (~8 occurrences) - Deployment status payloads
- [ ] `teleclaude/core/command_handlers.py` (~5 remaining) - Handler returns

## Keep Loose (No Changes)

These files intentionally use loose typing:
- `teleclaude/utils/transcript.py` - External JSONL parsing
- `teleclaude/adapters/redis_adapter.py` - Excluded from scope
- `teleclaude/core/events.py` - `raw` fields for agent hook data
- All `from_dict` method parameters - Input validation pattern
- All `asdict()` returns - Serialization output

## Testing Strategy

After each group:
1. Run `make lint` - Verify mypy passes
2. Run `make test` - Verify no runtime breakage
3. Commit the group

## Success Metrics

- [ ] `dict[str, object]` count reduced from ~130 to ~65 (50%+ reduction)
- [ ] `make lint` passes
- [ ] `make test` passes
- [ ] No new circular import warnings
