# Protocol-Based Architecture Guide

**Last Updated:** 2025-01-08

This document explains TeleClaude's Protocol-based architecture for cross-computer orchestration.

---

## Overview

TeleClaude uses Python's `Protocol` pattern to distinguish between two types of adapters:

1. **UI Adapters** - Human-facing platforms (Telegram, Slack)
2. **Transport Adapters** - Cross-computer messaging (Redis, Postgres)

This separation enables clean architecture where:
- **Message broadcasting** uses all adapters with `has_ui=True`
- **Cross-computer orchestration** uses only transport adapters implementing `RemoteExecutionProtocol`

---

## RemoteExecutionProtocol

Transport adapters implement this protocol to enable AI-to-AI communication:

```python
from typing import Protocol, AsyncIterator, List, Optional, Dict, runtime_checkable

@runtime_checkable
class RemoteExecutionProtocol(Protocol):
    """Protocol for adapters that can orchestrate commands on remote computers."""

    async def send_command_to_computer(
        self,
        computer_name: str,
        session_id: str,
        command: str,
        metadata: Optional[Dict[str, object]] = None,
    ) -> str:
        """Send command to remote computer. Returns request_id."""

    def poll_output_stream(
        self,
        session_id: str,
        timeout: float = 300.0,
    ) -> AsyncIterator[str]:
        """Stream output from remote session."""

    async def discover_computers(self) -> List[str]:
        """Discover available remote computers."""
```

### Who Implements This Protocol?

✅ **Transport Adapters:**
- `RedisAdapter` - Redis Streams (production)
- `PostgresAdapter` - PostgreSQL LISTEN/NOTIFY (future)
- Any custom transport adapter for cross-computer messaging

❌ **UI Adapters:**
- `TelegramAdapter` - Chat platform, not a transport layer
- `SlackAdapter` - Chat platform, not a transport layer

---

## AdapterClient: The Central Hub

**ALL adapter operations flow through AdapterClient.** No direct adapter references anywhere.

### Two Types of Operations

#### 1. Message Broadcasting (Local Sessions)

Distributes terminal output to all connected clients.

```python
# Used by: Daemon, OutputPoller
await adapter_client.send_message(session_id, "Terminal output here")
```

**Behavior:**
- Sends to **origin adapter** (CRITICAL - failure throws exception)
- Broadcasts to **observer adapters** with `has_ui=True` (best-effort)
- RedisAdapter skipped (has_ui=False, pure transport)

#### 2. Cross-Computer Orchestration (Remote Sessions)

Executes commands on remote computers via transport adapters.

```python
# Used by: MCP Server
await adapter_client.send_remote_command(computer_name, session_id, command)
async for chunk in adapter_client.poll_remote_output(session_id):
    yield chunk
computers = await adapter_client.discover_remote_computers()
```

**Behavior:**
- Routes to **first adapter implementing RemoteExecutionProtocol**
- Raises `RuntimeError` if no transport adapter available
- Aggregates results from multiple transport adapters (discover_computers)

---

## MCP Server Integration

The MCP server exposes tools for Claude Code to interact with remote computers.

### Before Refactoring ❌

```python
class TeleClaudeMCPServer:
    def __init__(self, redis_adapter, adapter_client, ...):
        self.redis_adapter = redis_adapter  # ❌ Direct reference

    async def list_projects(self, computer: str):
        # ❌ Bypasses AdapterClient
        await self.redis_adapter.send_command_to_computer(...)
        async for chunk in self.redis_adapter.poll_output_stream(...):
            yield chunk
```

### After Refactoring ✅

```python
class TeleClaudeMCPServer:
    def __init__(self, adapter_client, terminal_bridge, session_manager):
        self.client = adapter_client  # ✅ ONLY dependency

    async def list_projects(self, computer: str):
        # ✅ Uses AdapterClient (adapter-agnostic)
        await self.client.send_remote_command(computer, session_id, "list_projects")
        async for chunk in self.client.poll_remote_output(session_id):
            yield chunk
```

**Benefits:**
- MCP server is adapter-agnostic
- Swapping Redis for Postgres requires ZERO MCP server changes
- Clean separation of concerns
- Easier to test (mock AdapterClient, not specific adapters)

---

## Adding a New Transport Adapter

To add a new transport adapter (e.g., PostgreSQL):

### 1. Implement RemoteExecutionProtocol

```python
from teleclaude.core.protocols import RemoteExecutionProtocol
from teleclaude.adapters.base_adapter import BaseAdapter

class PostgresAdapter(BaseAdapter, RemoteExecutionProtocol):
    """PostgreSQL LISTEN/NOTIFY transport adapter."""

    has_ui = False  # Pure transport, no UI

    async def send_command_to_computer(
        self, computer_name: str, session_id: str, command: str, metadata=None
    ) -> str:
        """Send command via NOTIFY."""
        # Implementation...

    def poll_output_stream(self, session_id: str, timeout: float) -> AsyncIterator[str]:
        """Stream output via LISTEN."""
        # Implementation...

    async def discover_computers(self) -> List[str]:
        """Discover computers via heartbeat table."""
        # Implementation...
```

### 2. Register Adapter in Config

```yaml
# config.yml
postgres:
  enabled: true
  connection_string: postgresql://user:pass@host/db
```

### 3. Load Adapter in AdapterClient

```python
# teleclaude/core/adapter_client.py
if config.postgres.enabled:
    from teleclaude.adapters.postgres_adapter import PostgresAdapter
    postgres_adapter = PostgresAdapter(self)
    self.adapters["postgres"] = postgres_adapter
```

### That's It!

**No other changes needed:**
- MCP server automatically uses new transport
- AdapterClient routes cross-computer operations to it
- Aggregates with existing transport adapters (discover_computers)

---

## Testing Protocol-Based Architecture

### Unit Tests

Test Protocol implementation and AdapterClient routing:

```python
# tests/unit/test_protocols.py
def test_redis_adapter_implements_protocol():
    """Verify RedisAdapter implements RemoteExecutionProtocol."""
    assert issubclass(RedisAdapter, RemoteExecutionProtocol)

# tests/unit/test_adapter_client_protocols.py
async def test_send_remote_command_success():
    """Test AdapterClient routes to transport adapter."""
    client = AdapterClient()
    client.register_adapter("redis", mock_transport_adapter)

    request_id = await client.send_remote_command("comp1", "sess", "ls")

    assert request_id == "req_123"
    mock_transport_adapter.send_command_to_computer.assert_called_once()
```

### Integration Tests

Test MCP server with AdapterClient:

```python
# tests/integration/test_mcp_redis.py
async def test_teleclaude_list_projects(mcp_server, mock_adapter_client):
    """Test MCP tool uses AdapterClient (not direct adapter)."""
    projects = await mcp_server.teleclaude__list_projects("computer1")

    assert isinstance(projects, list)
    mock_adapter_client.send_remote_command.assert_called_once()
```

---

## Architecture Principles

1. **AdapterClient = Central Hub** - ALL adapter operations flow through it
2. **Protocol-Based Capabilities** - Use `isinstance(adapter, RemoteExecutionProtocol)` to check
3. **No Direct Adapter References** - MCP server, Daemon, etc. ONLY use AdapterClient
4. **Separation of Concerns** - Message broadcasting ≠ Cross-computer orchestration
5. **Runtime Type Checking** - `@runtime_checkable` Protocol enables `isinstance()` checks
6. **Adapter Agnostic** - Higher-level code doesn't know/care which transport is used

---

## Benefits of Protocol-Based Design

### Extensibility

- Add PostgresAdapter without changing MCP server
- Add SlackAdapter without affecting cross-computer logic
- Mix and match adapters dynamically

### Testability

- Mock AdapterClient instead of specific adapters
- Test Protocol compliance in isolation
- Integration tests don't depend on Redis/Postgres

### Maintainability

- Clear separation: UI platforms vs transport layers
- Single source of truth (AdapterClient)
- Type-safe protocol verification

### Type Safety

- `@runtime_checkable` enables `isinstance()` checks
- Mypy verifies Protocol compliance
- Clear interface contracts

---

## Migration Path

If adding Protocol support to existing code:

1. **Create Protocol** - Define interface in `protocols.py`
2. **Implement Protocol** - Make adapter inherit from Protocol
3. **Add AdapterClient Methods** - Delegate to Protocol-implementing adapters
4. **Refactor Consumers** - Replace direct adapter calls with AdapterClient methods
5. **Update Tests** - Mock AdapterClient, not adapters
6. **Update Docs** - Document Protocol pattern

---

## Related Documentation

- [Architecture Reference](./architecture.md) - Full system architecture
- [Multi-Computer Setup](./multi-computer-setup.md) - User-facing setup guide
- [Troubleshooting](./troubleshooting.md) - Common issues and solutions

---

**End of Protocol Architecture Guide**
