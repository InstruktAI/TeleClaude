# MCP Architecture

TeleClaude provides MCP (Model Context Protocol) tools for remote session management via a resilient two-layer architecture:

```
MCP Client (Claude Code/Codex)
    ↓ stdio
bin/mcp-wrapper.py (resilient proxy)
    ↓ unix socket (/tmp/teleclaude.sock)
teleclaude/mcp_server.py (backend)
    ↓
TeleClaude Daemon
```

## Architecture Layers

### Layer 1: MCP Wrapper (`bin/mcp-wrapper.py`)

**Purpose**: Resilient proxy that provides zero-downtime during backend restarts.

**Key Features**:
- **Cached handshake** - Responds to `initialize` immediately with pre-built capabilities
- **Hybrid mode** - Waits 500ms for backend; uses cache if unavailable
- **Auto-reconnection** - Transparently reconnects to backend when it restarts
- **Tool filtering** - Hides internal tools (e.g., `teleclaude__handle_agent_event`) from clients
- **Context injection** - Automatically injects `TELECLAUDE_SESSION_ID` into tool calls

**Configuration**:
```bash
# .env
MCP_DISABLE_STATIC_HANDSHAKE=false  # Enable cached handshake (default)
MCP_DISABLE_STATIC_HANDSHAKE=true   # Always proxy to backend (testing mode)
```

**Operation**:
1. Client connects → wrapper responds immediately with cached capabilities
2. Wrapper connects to backend socket (async, non-blocking)
3. Subsequent requests proxied to backend
4. If backend restarts, wrapper reconnects transparently

### Layer 2: MCP Server (`teleclaude/mcp_server.py`)

**Purpose**: Actual MCP tool implementation using `mcp` library.

**Provides 10 public tools**:
- `teleclaude__list_computers` - List available remote computers
- `teleclaude__list_projects` - List trusted project directories on a computer
- `teleclaude__list_sessions` - List active AI sessions
- `teleclaude__start_session` - Start a new AI session on a remote computer
- `teleclaude__send_message` - Send message to an existing session
- `teleclaude__get_session_data` - Retrieve session transcript and state
- `teleclaude__deploy_to_all_computers` - Deploy latest code via git pull
- `teleclaude__send_file` - Send file to a session's Telegram chat
- `teleclaude__stop_notifications` - Unsubscribe from session events
- `teleclaude__end_session` - Gracefully terminate a session

**Plus 1 internal tool** (hidden from clients):
- `teleclaude__handle_agent_event` - Used by hooks to emit events

**Integration**:
- Runs as part of the main daemon process
- Listens on `/tmp/teleclaude.sock`
- Uses shared database, Redis, and Telegram adapter

## Zero-Downtime Restart Flow

1. **Normal operation**: Client → Wrapper → Backend → Daemon
2. **`make restart` called**: Backend socket closes
3. **Wrapper detects disconnect**: Continues accepting client requests
4. **New client connects**: Wrapper responds with cached handshake immediately
5. **Wrapper reconnects**: Establishes new backend connection (async)
6. **Client requests**: Buffered until backend ready, then forwarded
7. **Existing clients**: Continue working transparently

**Result**: Clients experience no disconnection, just brief latency increase during restart.

## Testing Modes

### Production Mode (Default)
```bash
# .env
MCP_DISABLE_STATIC_HANDSHAKE=false
```
- 500ms backend timeout → cached response fallback
- Zero-downtime during restarts
- Best for production use

### Testing Mode
```bash
# .env
MCP_DISABLE_STATIC_HANDSHAKE=true
```
- Infinite backend timeout → always waits
- Ensures real MCP SDK protocol version
- Best for debugging client compatibility issues

## Logs

Monitor MCP operations:
```bash
tail -f logs/mcp-wrapper.log    # Wrapper activity (handshakes, connections)
tail -f logs/mcp_server.log     # Backend tool calls and responses
```

## Tool Filtering

Internal tools are filtered at two points:

1. **Wrapper cached response** - `teleclaude__handle_agent_event` excluded from `TOOL_NAMES`
2. **Runtime filtering** - Wrapper intercepts `tools/list` responses and removes internal tools

This ensures internal tools remain functional for hooks while being invisible to MCP clients.

## Debugging

**Wrapper not connecting**:
```bash
# Check if socket exists
ls -la /tmp/teleclaude.sock

# Check wrapper logs
tail -30 logs/mcp-wrapper.log

# Check if backend is running
make status
```

**Tools not working**:
```bash
# Check backend logs
tail -50 logs/mcp_server.log | grep ERROR

# Check daemon health
make status

# Verify database access
sqlite3 teleclaude.db "SELECT COUNT(*) FROM sessions;"
```

**Protocol version issues**:
```bash
# Test with real backend protocol
export MCP_DISABLE_STATIC_HANDSHAKE=true
make restart
# Then restart client to reconnect
```

## Implementation Details

**Pre-built response template**:
- Tools extracted at wrapper startup by parsing `mcp_server.py`
- JSON template pre-serialized with `__REQUEST_ID__` placeholder
- Handshake completes in <1ms via simple string replacement

**Connection management**:
- Backend connection retries every 5s with exponential backoff
- Client requests buffered when backend unavailable
- Reconnection happens transparently in background

**Context injection**:
- `TELECLAUDE_SESSION_ID` env var automatically added to tool call arguments
- Enables AI-to-AI caller identification in remote sessions
