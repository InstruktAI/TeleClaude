# TeleClaude REST API & MCP Server Specification

## Overview

The TeleClaude REST API enables programmatic control of terminal sessions across multiple computers. Combined with the MCP (Model Context Protocol) server, this allows Claude Code to orchestrate complex multi-server operations, automate deployments, and manage infrastructure directly from natural language commands.

**Architecture:**
```
┌─────────────────────────────────────────────┐
│  Claude Code (Local)                        │
│  "Deploy app to server1 and check logs"    │
└─────────────────┬───────────────────────────┘
                  │ MCP Protocol
                  ▼
┌─────────────────────────────────────────────┐
│  TeleClaude MCP Server (mcp-teleclaude)     │
│  - Manages SSH tunnels on-demand            │
│  - Exposes tools for Claude Code            │
│  - HTTP client to REST APIs                 │
└─────────────────┬───────────────────────────┘
                  │ HTTP over SSH Tunnels
    ┌─────────────┼─────────────┐
    │             │             │
    ▼             ▼             ▼
┌─────────┐  ┌─────────┐  ┌─────────┐
│  Mac    │  │ Server1 │  │ ProdDB  │
│  REST   │  │ REST    │  │ REST    │
│  API    │  │ API     │  │ API     │
│  :9999  │  │ :9999   │  │ :9999   │
└────┬────┘  └────┬────┘  └────┬────┘
     │            │             │
     ▼            ▼             ▼
 TeleClaude   TeleClaude   TeleClaude
  Daemon       Daemon       Daemon
```

---

## Security Model

### SSH Tunnel Architecture

**Core Principle:** REST API is **never** exposed to the internet. All communication goes through SSH tunnels.

**Design:**
1. REST API binds to `127.0.0.1` only
2. MCP server establishes SSH tunnels on-demand (lazy initialization)
3. API calls routed through encrypted SSH connection
4. API key validation is **optional** (default: disabled)

**Why SSH Tunnels:**
- ✅ Zero attack surface (API not exposed)
- ✅ No HTTPS certificate management
- ✅ Leverages existing SSH infrastructure
- ✅ Battle-tested security model
- ✅ Simpler than custom authentication
- ✅ Works seamlessly with SSH keys

**Requirements:**
- Passwordless SSH key authentication between computers (REQUIRED)
- SSH keys configured before MCP server startup
- No password-based SSH allowed

### API Key (Optional)

**Default:** Disabled (`require_api_key: false`)

**When to enable:**
- Shared servers with multiple SSH users
- Defense-in-depth paranoia mode
- Future: multi-user session sharing

**Configuration:**
```yaml
# config.yml on TeleClaude daemon
rest_api:
  enabled: true
  bind_address: 127.0.0.1  # NEVER 0.0.0.0
  port: 9999
  require_api_key: false
  api_key: ${REST_API_KEY}  # Only if require_api_key: true
```

---

## REST API Specification

### Base URL
```
http://127.0.0.1:9999/api/v1
```

### Authentication
Optional `X-TeleClaude-API-Key` header (only if `require_api_key: true`):
```
X-TeleClaude-API-Key: your_api_key_here
```

### Common Response Format

**Success:**
```json
{
  "success": true,
  "data": { ... },
  "timestamp": "2025-10-29T10:30:00Z"
}
```

**Error:**
```json
{
  "success": false,
  "error": {
    "code": "SESSION_NOT_FOUND",
    "message": "Session abc123 does not exist"
  },
  "timestamp": "2025-10-29T10:30:00Z"
}
```

### Error Codes
- `UNAUTHORIZED` - Invalid API key (401)
- `SESSION_NOT_FOUND` - Session doesn't exist (404)
- `SESSION_DEAD` - tmux session died (410)
- `INVALID_REQUEST` - Malformed request (400)
- `INTERNAL_ERROR` - Server error (500)
- `RATE_LIMITED` - Too many requests (429)

---

## Endpoints

### Session Management

#### Create Session
```http
POST /api/v1/sessions
Content-Type: application/json

{
  "title": "debugging auth flow",  // optional
  "working_dir": "~/projects",     // optional, default from config
  "terminal_size": "120x40"        // optional, default from config
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "tmux_session_name": "mac-debugging-auth-flow",
    "title": "[Mac] debugging auth flow",
    "working_dir": "/Users/maurice/projects",
    "status": "active",
    "created_at": "2025-10-29T10:30:00Z"
  }
}
```

#### List Sessions
```http
GET /api/v1/sessions?status=active&computer=Mac
```

**Response:**
```json
{
  "success": true,
  "data": {
    "sessions": [
      {
        "session_id": "550e8400...",
        "title": "[Mac] debugging auth flow",
        "status": "active",
        "last_activity": "2025-10-29T10:35:00Z",
        "created_at": "2025-10-29T10:30:00Z"
      }
    ],
    "total": 1
  }
}
```

#### Get Session Info
```http
GET /api/v1/sessions/{session_id}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "session_id": "550e8400...",
    "title": "[Mac] debugging auth flow",
    "tmux_session_name": "mac-debugging-auth-flow",
    "status": "active",
    "current_working_dir": "/Users/maurice/projects/teleclaude",
    "terminal_size": "120x40",
    "command_count": 12,
    "created_at": "2025-10-29T10:30:00Z",
    "last_activity": "2025-10-29T10:35:00Z"
  }
}
```

#### Close Session
```http
DELETE /api/v1/sessions/{session_id}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "message": "Session closed successfully"
  }
}
```

---

### Command Execution

#### Send Command
```http
POST /api/v1/sessions/{session_id}/input
Content-Type: application/json

{
  "command": "ls -la",
  "wait_for_completion": false  // optional, default: false
}
```

**Response (immediate):**
```json
{
  "success": true,
  "data": {
    "message": "Command sent to session"
  }
}
```

**Response (wait_for_completion: true):**
```json
{
  "success": true,
  "data": {
    "output": "total 48\ndrwxr-xr-x  12 maurice  staff  384 Oct 29 10:30 .\n...",
    "exit_code": 0,
    "duration_ms": 125
  }
}
```

#### Get Output
```http
GET /api/v1/sessions/{session_id}/output?lines=50&from_line=0
```

**Query Parameters:**
- `lines` - Number of lines to return (default: all)
- `from_line` - Start from line N (default: 0)

**Response:**
```json
{
  "success": true,
  "data": {
    "output": "$ ls -la\ntotal 48\ndrwxr-xr-x  12 maurice  staff  384 Oct 29 10:30 .",
    "total_lines": 50,
    "from_line": 0,
    "to_line": 50
  }
}
```

---

### Output & History Access

#### Get Specific Message
```http
GET /api/v1/sessions/{session_id}/messages?index=last
GET /api/v1/sessions/{session_id}/messages?index=-2  // second to last
GET /api/v1/sessions/{session_id}/messages?index=5   // 6th message
```

**Response:**
```json
{
  "success": true,
  "data": {
    "index": 5,
    "message": "$ npm install\nadded 247 packages in 12s",
    "timestamp": "2025-10-29T10:35:00Z",
    "type": "output"  // or "command", "system"
  }
}
```

#### Get Message Range
```http
GET /api/v1/sessions/{session_id}/messages?from=10&limit=5
```

**Response:**
```json
{
  "success": true,
  "data": {
    "messages": [
      {"index": 10, "message": "$ cd src", "timestamp": "...", "type": "command"},
      {"index": 11, "message": "$ ls", "timestamp": "...", "type": "command"},
      {"index": 12, "message": "index.ts  utils.ts", "timestamp": "...", "type": "output"}
    ],
    "from": 10,
    "limit": 5,
    "total": 3
  }
}
```

#### Get Command History
```http
GET /api/v1/sessions/{session_id}/history?limit=20
```

**Response:**
```json
{
  "success": true,
  "data": {
    "history": [
      {"index": 1, "command": "cd ~/projects", "timestamp": "2025-10-29T10:30:00Z"},
      {"index": 2, "command": "ls -la", "timestamp": "2025-10-29T10:30:15Z"},
      {"index": 3, "command": "npm install", "timestamp": "2025-10-29T10:31:00Z"}
    ],
    "total": 3
  }
}
```

---

### Recording Access

#### Get Video Recording
```http
GET /api/v1/sessions/{session_id}/recordings/video?duration=10m
```

**Query Parameters:**
- `duration` - Time window: `5m`, `10m`, `20m` (default: `20m`)
- `format` - Response format: `url` or `base64` (default: `url`)

**Response (format=url):**
```json
{
  "success": true,
  "data": {
    "video_url": "/api/v1/recordings/temp/abc123.gif",
    "duration_seconds": 600,
    "size_bytes": 2457600,
    "expires_at": "2025-10-29T11:00:00Z"  // URL valid for 30 min
  }
}
```

**Response (format=base64):**
```json
{
  "success": true,
  "data": {
    "video_base64": "R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw==",
    "duration_seconds": 600,
    "size_bytes": 2457600
  }
}
```

#### Get Text Recording
```http
GET /api/v1/sessions/{session_id}/recordings/text?duration=5m
```

**Response:**
```json
{
  "success": true,
  "data": {
    "text": "$ npm install\nadded 247 packages in 12s\n$ npm run build\n...",
    "duration_seconds": 300,
    "lines": 156
  }
}
```

---

### Directory & File Operations

#### Change Directory
```http
POST /api/v1/sessions/{session_id}/cd
Content-Type: application/json

{
  "path": "~/projects"  // or empty to get quick paths
}
```

**Response (with path):**
```json
{
  "success": true,
  "data": {
    "previous_dir": "/Users/maurice",
    "current_dir": "/Users/maurice/projects"
  }
}
```

**Response (no path - returns quick paths):**
```json
{
  "success": true,
  "data": {
    "current_dir": "/Users/maurice",
    "quick_paths": [
      {"name": "Projects", "path": "~/projects"},
      {"name": "Logs", "path": "/var/log"},
      {"name": "Temp", "path": "/tmp"}
    ]
  }
}
```

#### Get Current Directory
```http
GET /api/v1/sessions/{session_id}/cwd
```

**Response:**
```json
{
  "success": true,
  "data": {
    "cwd": "/Users/maurice/projects/teleclaude"
  }
}
```

#### List Directory
```http
GET /api/v1/sessions/{session_id}/ls?path=/var/log&details=true
```

**Query Parameters:**
- `path` - Directory to list (default: current working dir)
- `details` - Include size, permissions, etc. (default: false)

**Response:**
```json
{
  "success": true,
  "data": {
    "path": "/var/log",
    "entries": [
      {
        "name": "system.log",
        "type": "file",
        "size": 2457600,
        "modified": "2025-10-29T10:00:00Z",
        "permissions": "-rw-r--r--"
      },
      {
        "name": "archive",
        "type": "directory",
        "size": 4096,
        "modified": "2025-10-28T15:00:00Z",
        "permissions": "drwxr-xr-x"
      }
    ]
  }
}
```

#### Read File
```http
GET /api/v1/sessions/{session_id}/files?path=/var/log/system.log&lines=50&tail=true
```

**Query Parameters:**
- `path` - File path (required)
- `lines` - Number of lines (default: all)
- `tail` - Read from end (default: false)

**Response:**
```json
{
  "success": true,
  "data": {
    "path": "/var/log/system.log",
    "content": "Oct 29 10:30:00 Error: Connection timeout\n...",
    "lines": 50,
    "total_lines": 15342,
    "size_bytes": 2457600
  }
}
```

#### Upload File
```http
POST /api/v1/sessions/{session_id}/files
Content-Type: multipart/form-data

file: <binary data>
path: /tmp/uploaded.txt  // optional, default: ~/telegram_uploads/
```

**Response:**
```json
{
  "success": true,
  "data": {
    "path": "/tmp/uploaded.txt",
    "size_bytes": 1024,
    "uploaded_at": "2025-10-29T10:30:00Z"
  }
}
```

---

### Session Control

#### Resize Terminal
```http
POST /api/v1/sessions/{session_id}/resize
Content-Type: application/json

{
  "size": "large"  // or "small", "medium", or "120x40"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "previous_size": "80x24",
    "new_size": "120x40"
  }
}
```

#### Send Signal
```http
POST /api/v1/sessions/{session_id}/signal
Content-Type: application/json

{
  "signal": "SIGINT"  // or "SIGTERM", "SIGKILL"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "message": "Signal SIGINT sent to session"
  }
}
```

#### Rename Session
```http
POST /api/v1/sessions/{session_id}/rename
Content-Type: application/json

{
  "title": "production deployment"
}
```

**Response:**
```json
{
  "success": true,
  "data": {
    "previous_title": "[Mac] debugging auth flow",
    "new_title": "[Mac] production deployment"
  }
}
```

#### Clear Screen
```http
POST /api/v1/sessions/{session_id}/clear
```

**Response:**
```json
{
  "success": true,
  "data": {
    "message": "Screen cleared"
  }
}
```

---

### Status & Config

#### Get Session Status
```http
GET /api/v1/sessions/{session_id}/status
```

**Response:**
```json
{
  "success": true,
  "data": {
    "status": "active",  // active, waiting, slow, stalled, idle, dead
    "status_emoji": "🟢",
    "last_output_at": "2025-10-29T10:35:00Z",
    "seconds_since_output": 5
  }
}
```

#### Get Daemon Status
```http
GET /api/v1/status
```

**Response:**
```json
{
  "success": true,
  "data": {
    "version": "0.1.0",
    "computer_name": "Mac",
    "uptime_seconds": 86400,
    "active_sessions": 3,
    "total_sessions": 5,
    "adapters": ["telegram", "rest"],
    "started_at": "2025-10-28T10:30:00Z"
  }
}
```

#### List Quick Paths
```http
GET /api/v1/config/quick_paths
```

**Response:**
```json
{
  "success": true,
  "data": {
    "quick_paths": [
      {"name": "Projects", "path": "~/projects"},
      {"name": "Logs", "path": "/var/log"},
      {"name": "Temp", "path": "/tmp"},
      {"name": "Config", "path": "~/.config"}
    ]
  }
}
```

#### Get Config
```http
GET /api/v1/config
```

**Response:**
```json
{
  "success": true,
  "data": {
    "computer_name": "Mac",
    "terminal": {
      "default_size": "80x24",
      "sizes": {
        "small": "60x24",
        "medium": "100x30",
        "large": "120x40"
      }
    },
    "quick_paths": [...],
    "recording_enabled": true
  }
}
```

---

## REST Adapter Implementation

### Technology Stack
- **Framework:** FastAPI (async, auto-docs, validation)
- **ASGI Server:** uvicorn
- **Validation:** Pydantic models

### Code Structure
```
teleclaude/adapters/rest_adapter.py
├── RestAdapter(BaseAdapter)
│   ├── __init__()
│   ├── start()  # Start FastAPI server
│   └── stop()   # Graceful shutdown
├── API route handlers
├── Request/response models (Pydantic)
└── Middleware (auth, logging, rate limiting)
```

### Authentication Middleware
```python
async def auth_middleware(request: Request, call_next):
    config = get_config()

    if not config['rest_api']['require_api_key']:
        return await call_next(request)

    api_key = request.headers.get('X-TeleClaude-API-Key')
    if api_key != config['rest_api']['api_key']:
        return JSONResponse(
            status_code=401,
            content={"success": false, "error": {"code": "UNAUTHORIZED", "message": "Invalid API key"}}
        )

    return await call_next(request)
```

### Rate Limiting
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/api/v1/sessions/{session_id}/input")
@limiter.limit("30/minute")  # 30 commands per minute per IP
async def send_input(session_id: str, request: Request):
    ...
```

### Example Route
```python
@app.post("/api/v1/sessions")
async def create_session(request: CreateSessionRequest):
    session = await daemon.session_manager.create_session(
        computer_name=daemon.config['computer_name'],
        title=request.title,
        working_dir=request.working_dir or daemon.config['working_dir'],
        terminal_size=request.terminal_size or daemon.config['terminal_size']
    )

    # Create tmux session
    await daemon.terminal_bridge.create_tmux_session(
        name=session.tmux_session_name,
        working_dir=session.working_directory,
        shell=daemon.config['shell']
    )

    # Start output streamer
    await daemon.start_output_streamer(session.session_id)

    return {"success": True, "data": session.dict()}
```

---

## MCP Server Specification

### Package: `mcp-teleclaude`

Separate repository/package that implements MCP protocol and manages TeleClaude instances.

### Configuration

**Location:** `~/.claude/mcp_config.json`

```json
{
  "mcpServers": {
    "teleclaude": {
      "command": "npx",
      "args": ["-y", "mcp-teleclaude"],
      "env": {
        "TELECLAUDE_CONFIG": "~/.teleclaude/mcp-instances.json"
      }
    }
  }
}
```

**Instance Config:** `~/.teleclaude/mcp-instances.json`

```json
{
  "instances": {
    "mac": {
      "url": "http://localhost:9999",
      "require_api_key": false
    },
    "server1": {
      "ssh": {
        "host": "server1.example.com"
      },
      "require_api_key": false
    },
    "server2": {
      "ssh": {
        "host": "server2.example.com",
        "user": "deploy"
      },
      "api_key": "key_server2",
      "require_api_key": true
    },
    "proddb": {
      "ssh": {
        "host": "proddb.example.com",
        "user": "dbadmin",
        "identity_file": "~/.ssh/prod_key"
      },
      "require_api_key": false
    }
  }
}
```

---

## MCP Tools

### Session Management

#### `teleclaude_create_session`
```typescript
{
  name: "teleclaude_create_session",
  description: "Create a new terminal session on a remote computer",
  inputSchema: {
    type: "object",
    properties: {
      computer: {
        type: "string",
        description: "Computer name (e.g., 'server1', 'proddb')",
        required: true
      },
      working_dir: {
        type: "string",
        description: "Initial working directory (default: ~)"
      },
      title: {
        type: "string",
        description: "Session title (optional, will be AI-generated if omitted)"
      }
    }
  }
}
```

**Returns:**
```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "computer": "server1",
  "title": "[Server1] New session",
  "working_dir": "/home/deploy"
}
```

#### `teleclaude_list_sessions`
```typescript
{
  name: "teleclaude_list_sessions",
  description: "List all active terminal sessions, optionally filtered by computer",
  inputSchema: {
    type: "object",
    properties: {
      computer: {
        type: "string",
        description: "Filter by computer name (optional)"
      }
    }
  }
}
```

#### `teleclaude_get_session_info`
```typescript
{
  name: "teleclaude_get_session_info",
  description: "Get detailed information about a specific session",
  inputSchema: {
    type: "object",
    properties: {
      session_id: {
        type: "string",
        description: "Session ID",
        required: true
      }
    }
  }
}
```

#### `teleclaude_close_session`
```typescript
{
  name: "teleclaude_close_session",
  description: "Close a terminal session",
  inputSchema: {
    type: "object",
    properties: {
      session_id: {
        type: "string",
        description: "Session ID to close",
        required: true
      }
    }
  }
}
```

---

### Command Execution

#### `teleclaude_send_command`
```typescript
{
  name: "teleclaude_send_command",
  description: "Send a command to a terminal session and optionally wait for completion",
  inputSchema: {
    type: "object",
    properties: {
      session_id: {
        type: "string",
        description: "Session ID",
        required: true
      },
      command: {
        type: "string",
        description: "Command to execute",
        required: true
      },
      wait_for_completion: {
        type: "boolean",
        description: "Wait for command to finish and return output (default: false)"
      }
    }
  }
}
```

**Example Usage:**
```
User: "Check if nginx is running on server1"
Claude: [uses teleclaude_send_command(session_id, "systemctl status nginx", wait_for_completion=true)]
```

#### `teleclaude_get_output`
```typescript
{
  name: "teleclaude_get_output",
  description: "Get recent output from a terminal session",
  inputSchema: {
    type: "object",
    properties: {
      session_id: {
        type: "string",
        required: true
      },
      lines: {
        type: "number",
        description: "Number of lines to retrieve (default: 50)"
      },
      from_line: {
        type: "number",
        description: "Start from line N (default: 0)"
      }
    }
  }
}
```

#### `teleclaude_get_message`
```typescript
{
  name: "teleclaude_get_message",
  description: "Get a specific message from session history by index",
  inputSchema: {
    type: "object",
    properties: {
      session_id: {
        type: "string",
        required: true
      },
      index: {
        type: "string",
        description: "Message index: 'last', '-2' (second to last), or '5' (6th message)",
        default: "last"
      }
    }
  }
}
```

#### `teleclaude_get_history`
```typescript
{
  name: "teleclaude_get_history",
  description: "Get command history for a session",
  inputSchema: {
    type: "object",
    properties: {
      session_id: {
        type: "string",
        required: true
      },
      limit: {
        type: "number",
        description: "Number of recent commands (default: 20)"
      }
    }
  }
}
```

---

### Navigation & Files

#### `teleclaude_list_quick_paths`
```typescript
{
  name: "teleclaude_list_quick_paths",
  description: "Get list of configured quick paths for a computer",
  inputSchema: {
    type: "object",
    properties: {
      computer: {
        type: "string",
        description: "Computer name",
        required: true
      }
    }
  }
}
```

#### `teleclaude_change_directory`
```typescript
{
  name: "teleclaude_change_directory",
  description: "Change working directory in a session. Omit path to see quick paths.",
  inputSchema: {
    type: "object",
    properties: {
      session_id: {
        type: "string",
        required: true
      },
      path: {
        type: "string",
        description: "Directory path or empty to list quick paths"
      }
    }
  }
}
```

#### `teleclaude_list_directory`
```typescript
{
  name: "teleclaude_list_directory",
  description: "List files in a directory",
  inputSchema: {
    type: "object",
    properties: {
      session_id: {
        type: "string",
        required: true
      },
      path: {
        type: "string",
        description: "Directory path (default: current working directory)"
      },
      details: {
        type: "boolean",
        description: "Include size, permissions, etc. (default: false)"
      }
    }
  }
}
```

#### `teleclaude_read_file`
```typescript
{
  name: "teleclaude_read_file",
  description: "Read contents of a file",
  inputSchema: {
    type: "object",
    properties: {
      session_id: {
        type: "string",
        required: true
      },
      path: {
        type: "string",
        description: "File path",
        required: true
      },
      lines: {
        type: "number",
        description: "Number of lines to read"
      },
      tail: {
        type: "boolean",
        description: "Read from end of file (default: false)"
      }
    }
  }
}
```

#### `teleclaude_upload_file`
```typescript
{
  name: "teleclaude_upload_file",
  description: "Upload a file to remote session",
  inputSchema: {
    type: "object",
    properties: {
      session_id: {
        type: "string",
        required: true
      },
      local_path: {
        type: "string",
        description: "Local file path to upload",
        required: true
      },
      remote_path: {
        type: "string",
        description: "Remote destination path (default: ~/telegram_uploads/)"
      }
    }
  }
}
```

---

### Recording

#### `teleclaude_get_video`
```typescript
{
  name: "teleclaude_get_video",
  description: "Get video recording of terminal session (GIF)",
  inputSchema: {
    type: "object",
    properties: {
      session_id: {
        type: "string",
        required: true
      },
      duration: {
        type: "string",
        description: "Time window: '5m', '10m', '20m' (default: '20m')"
      }
    }
  }
}
```

**Returns:** URL to download GIF or base64-encoded GIF data

#### `teleclaude_get_text_output`
```typescript
{
  name: "teleclaude_get_text_output",
  description: "Get text transcript of terminal session",
  inputSchema: {
    type: "object",
    properties: {
      session_id: {
        type: "string",
        required: true
      },
      duration: {
        type: "string",
        description: "Time window: '5m', '10m', '20m' (default: '20m')"
      }
    }
  }
}
```

---

### Control

#### `teleclaude_resize`
```typescript
{
  name: "teleclaude_resize",
  description: "Resize terminal window",
  inputSchema: {
    type: "object",
    properties: {
      session_id: {
        type: "string",
        required: true
      },
      size: {
        type: "string",
        description: "Size preset: 'small', 'medium', 'large' or dimensions like '120x40'",
        required: true
      }
    }
  }
}
```

#### `teleclaude_cancel`
```typescript
{
  name: "teleclaude_cancel",
  description: "Send SIGINT (Ctrl+C) to interrupt running command",
  inputSchema: {
    type: "object",
    properties: {
      session_id: {
        type: "string",
        required: true
      }
    }
  }
}
```

#### `teleclaude_rename`
```typescript
{
  name: "teleclaude_rename",
  description: "Rename a session",
  inputSchema: {
    type: "object",
    properties: {
      session_id: {
        type: "string",
        required: true
      },
      title: {
        type: "string",
        description: "New title",
        required: true
      }
    }
  }
}
```

---

### Status

#### `teleclaude_get_status`
```typescript
{
  name: "teleclaude_get_status",
  description: "Get current status of a session (active, idle, etc.)",
  inputSchema: {
    type: "object",
    properties: {
      session_id: {
        type: "string",
        required: true
      }
    }
  }
}
```

#### `teleclaude_get_daemon_status`
```typescript
{
  name: "teleclaude_get_daemon_status",
  description: "Get daemon status for a computer (uptime, session count, etc.)",
  inputSchema: {
    type: "object",
    properties: {
      computer: {
        type: "string",
        description: "Computer name",
        required: true
      }
    }
  }
}
```

---

### Advanced Tools (Future)

#### `teleclaude_broadcast_command`
```typescript
{
  name: "teleclaude_broadcast_command",
  description: "Run command on multiple computers in parallel",
  inputSchema: {
    type: "object",
    properties: {
      computers: {
        type: "array",
        items: { type: "string" },
        description: "List of computer names",
        required: true
      },
      command: {
        type: "string",
        description: "Command to execute",
        required: true
      }
    }
  }
}
```

#### `teleclaude_quick_command`
```typescript
{
  name: "teleclaude_quick_command",
  description: "Create session, run command, return output, close session (convenience)",
  inputSchema: {
    type: "object",
    properties: {
      computer: {
        type: "string",
        required: true
      },
      command: {
        type: "string",
        required: true
      },
      working_dir: {
        type: "string"
      }
    }
  }
}
```

---

## MCP Resources

### `teleclaude://computers`
List all configured TeleClaude instances with their status.

**Response:**
```json
{
  "uri": "teleclaude://computers",
  "mimeType": "application/json",
  "text": {
    "computers": [
      {"name": "mac", "status": "online", "sessions": 2},
      {"name": "server1", "status": "online", "sessions": 5},
      {"name": "proddb", "status": "offline", "sessions": 0}
    ]
  }
}
```

### `teleclaude://{computer}/sessions`
List all sessions for a specific computer.

### `teleclaude://{computer}/config`
Get current configuration for a computer.

---

## MCP Server Implementation

### On-Demand SSH Tunnel Management

```typescript
class TeleClaude {
  private tunnels: Map<string, SSHTunnel> = new Map();
  private config: InstanceConfig;

  // Establish tunnel on first use
  async ensureTunnel(computer: string): Promise<number> {
    if (!this.tunnels.has(computer) || !this.tunnels.get(computer)!.isAlive()) {
      const sshConfig = this.config.instances[computer].ssh;

      if (!sshConfig) {
        // Local instance, no tunnel needed
        return this.config.instances[computer].port || 9999;
      }

      // Create SSH tunnel
      const tunnel = new SSHTunnel({
        host: sshConfig.host,
        user: sshConfig.user || process.env.USER,
        remotePort: 9999,
        localPort: this.getNextAvailablePort(),
        identityFile: sshConfig.identity_file
      });

      await tunnel.connect();
      this.tunnels.set(computer, tunnel);
    }

    return this.tunnels.get(computer)!.localPort;
  }

  // Tool implementation
  async teleclaude_send_command(args: {
    session_id: string;
    command: string;
    wait_for_completion?: boolean;
  }) {
    // Get computer from session_id (stored in-memory map)
    const computer = this.getComputerFromSession(args.session_id);

    // Establish tunnel (no-op if already exists)
    const localPort = await this.ensureTunnel(computer);

    // Make API call
    const url = `http://localhost:${localPort}/api/v1/sessions/${args.session_id}/input`;
    const response = await fetch(url, {
      method: 'POST',
      headers: this.getHeaders(computer),
      body: JSON.stringify({
        command: args.command,
        wait_for_completion: args.wait_for_completion
      })
    });

    return await response.json();
  }

  private getHeaders(computer: string): Record<string, string> {
    const config = this.config.instances[computer];
    const headers: Record<string, string> = {
      'Content-Type': 'application/json'
    };

    if (config.require_api_key && config.api_key) {
      headers['X-TeleClaude-API-Key'] = config.api_key;
    }

    return headers;
  }

  // Cleanup on shutdown
  async cleanup() {
    for (const [computer, tunnel] of this.tunnels) {
      await tunnel.close();
    }
  }
}
```

### SSH Tunnel Class

```typescript
import { spawn } from 'child_process';
import { promisify } from 'util';
import { exec } from 'child_process';

const execAsync = promisify(exec);

class SSHTunnel {
  private process: any;
  public localPort: number;
  private config: SSHTunnelConfig;

  constructor(config: SSHTunnelConfig) {
    this.config = config;
    this.localPort = config.localPort;
  }

  async connect(): Promise<void> {
    const args = [
      '-N',  // Don't execute remote command
      '-L', `${this.localPort}:localhost:${this.config.remotePort}`,
      '-o', 'BatchMode=yes',  // Non-interactive
      '-o', 'StrictHostKeyChecking=accept-new'
    ];

    if (this.config.identityFile) {
      args.push('-i', this.config.identityFile);
    }

    const destination = this.config.user
      ? `${this.config.user}@${this.config.host}`
      : this.config.host;

    args.push(destination);

    this.process = spawn('ssh', args, {
      stdio: 'ignore',
      detached: false
    });

    // Wait for tunnel to be ready
    await this.waitForTunnel();
  }

  private async waitForTunnel(maxAttempts = 10): Promise<void> {
    for (let i = 0; i < maxAttempts; i++) {
      try {
        // Try to connect to local port
        const response = await fetch(`http://localhost:${this.localPort}/api/v1/health`);
        if (response.ok) return;
      } catch (e) {
        // Not ready yet, wait
      }
      await new Promise(resolve => setTimeout(resolve, 500));
    }
    throw new Error(`SSH tunnel to ${this.config.host} failed to establish`);
  }

  isAlive(): boolean {
    return this.process && !this.process.killed;
  }

  async close(): Promise<void> {
    if (this.process) {
      this.process.kill();
      this.process = null;
    }
  }
}
```

---

## Setup Guide

### 1. SSH Key Configuration (REQUIRED)

**Generate SSH key (if you don't have one):**
```bash
ssh-keygen -t ed25519 -C "teleclaude"
# Press Enter for default location (~/.ssh/id_ed25519)
# Optional: set passphrase (or leave empty for passwordless)
```

**Copy key to all remote servers:**
```bash
ssh-copy-id user@server1.example.com
ssh-copy-id user@server2.example.com
ssh-copy-id dbadmin@proddb.example.com
```

**Test passwordless SSH:**
```bash
ssh user@server1.example.com echo "success"
# Should print "success" without password prompt
```

### 2. TeleClaude Daemon Setup

**On each computer (Mac, servers), enable REST API:**

Edit `config.yml`:
```yaml
rest_api:
  enabled: true
  bind_address: 127.0.0.1  # CRITICAL: localhost only!
  port: 9999
  require_api_key: false  # Default: no API key needed with SSH tunnels
```

Restart daemon:
```bash
teleclaude restart
```

Verify REST API is running:
```bash
curl http://127.0.0.1:9999/api/v1/health
# Should return: {"status": "ok", "version": "0.1.0"}
```

### 3. MCP Server Installation

**Install via npm:**
```bash
npm install -g mcp-teleclaude
```

**Create instance config:**
```bash
mkdir -p ~/.teleclaude
nano ~/.teleclaude/mcp-instances.json
```

```json
{
  "instances": {
    "mac": {
      "url": "http://localhost:9999"
    },
    "server1": {
      "ssh": {
        "host": "server1.example.com"
      }
    },
    "proddb": {
      "ssh": {
        "host": "proddb.example.com",
        "user": "dbadmin"
      }
    }
  }
}
```

**Configure Claude Code:**

Edit `~/.claude/mcp_config.json`:
```json
{
  "mcpServers": {
    "teleclaude": {
      "command": "mcp-teleclaude",
      "env": {
        "TELECLAUDE_CONFIG": "~/.teleclaude/mcp-instances.json"
      }
    }
  }
}
```

**Test MCP server:**
```bash
mcp-teleclaude --test
# Should list all instances and verify connectivity
```

### 4. Validation

**Test from Claude Code:**
```
User: "List all TeleClaude instances"
Claude: [calls teleclaude_list_computers()]
         Mac (online, 2 sessions)
         Server1 (online, 5 sessions)
         ProdDB (online, 0 sessions)

User: "Check free disk space on server1"
Claude: [creates session on server1]
        [runs: df -h]
        [returns output]
```

---

## Usage Examples

### Example 1: Single Server Command

**User:** "Check if nginx is running on server1"

**Claude's Actions:**
1. `teleclaude_create_session(computer="server1", working_dir="~")`
   → Returns `session_id: "abc123"`
2. `teleclaude_send_command(session_id="abc123", command="systemctl status nginx", wait_for_completion=true)`
   → Returns output
3. `teleclaude_close_session(session_id="abc123")`

**Result:** Claude reports nginx status to user

---

### Example 2: Multi-Server Log Search

**User:** "Search for error 'connection timeout' in logs on all servers"

**Claude's Actions:**
1. `teleclaude_list_computers()` → Get list: [mac, server1, server2]
2. In parallel:
   - `teleclaude_create_session(computer="server1")` → `session_id: "s1"`
   - `teleclaude_create_session(computer="server2")` → `session_id: "s2"`
3. In parallel:
   - `teleclaude_send_command(session_id="s1", command="grep 'connection timeout' /var/log/*.log")`
   - `teleclaude_send_command(session_id="s2", command="grep 'connection timeout' /var/log/*.log")`
4. Wait for both to complete
5. `teleclaude_get_output(session_id="s1")`
6. `teleclaude_get_output(session_id="s2")`
7. Close both sessions

**Result:** Aggregated log results from all servers

---

### Example 3: Deployment Workflow

**User:** "Deploy the latest code to production"

**Claude's Actions:**
1. `teleclaude_create_session(computer="proddb", working_dir="/opt/app")`
2. `teleclaude_send_command(session_id, "git pull origin main", wait_for_completion=true)`
3. Check output for errors
4. `teleclaude_send_command(session_id, "npm install", wait_for_completion=true)`
5. `teleclaude_send_command(session_id, "npm run build", wait_for_completion=true)`
6. `teleclaude_send_command(session_id, "pm2 restart app")`
7. Wait 5 seconds
8. `teleclaude_send_command(session_id, "curl http://localhost:3000/health")`
9. Verify health check passes
10. Keep session open for monitoring

**Result:** Full deployment with validation, session remains for debugging if needed

---

### Example 4: File Operations

**User:** "Copy my local config.json to server1 and restart the service"

**Claude's Actions:**
1. `teleclaude_create_session(computer="server1", working_dir="/opt/app")`
2. `teleclaude_upload_file(session_id, local_path="~/config.json", remote_path="/opt/app/config.json")`
3. `teleclaude_send_command(session_id, "systemctl restart myapp")`
4. `teleclaude_send_command(session_id, "systemctl status myapp", wait_for_completion=true)`
5. Verify service restarted successfully

---

### Example 5: Monitoring & Recording

**User:** "I ran a build command but it failed. Can you show me what happened?"

**Claude's Actions:**
1. Identify session where build ran
2. `teleclaude_get_video(session_id, duration="5m")`
3. Show user the GIF of terminal output
4. Analyze text output to diagnose error
5. Suggest fix

---

## Security Checklist

- [ ] REST API binds to `127.0.0.1` ONLY (never `0.0.0.0`)
- [ ] Passwordless SSH key auth configured for all servers
- [ ] SSH keys have proper permissions (600 for private key)
- [ ] Firewall rules: block external access to port 9999
- [ ] API keys disabled by default (`require_api_key: false`)
- [ ] Audit logging enabled for all API calls
- [ ] Rate limiting configured (30 req/min per session)
- [ ] MCP config file has proper permissions (600)
- [ ] Consider: dedicated SSH user for TeleClaude operations
- [ ] Consider: SSH key rotation policy

---

## Future Enhancements

### Multi-User Session Sharing
- Enable API key per user
- Add session permissions (read-only vs read-write)
- Telegram: invite users to session topic
- Everyone sees live output
- Only owner can send commands (or configurable)

### WebSocket Streaming
- Replace polling with WebSocket for live output
- Push output to Claude Code in real-time
- Better for long-running commands

### Session Templates
- Pre-configured session setups
- E.g., "Production Deploy" template: cd /opt/app, git pull, npm install, etc.
- One-click launch with `teleclaude_create_from_template(template="prod-deploy")`

### Audit & Monitoring
- Centralized audit log across all instances
- Dashboard: real-time view of all sessions
- Alerts: notify when specific patterns detected

---

## Troubleshooting

### SSH Tunnel Fails
```
Error: SSH tunnel to server1.example.com failed to establish
```

**Solutions:**
- Verify SSH key auth: `ssh user@server1.example.com echo ok`
- Check SSH config: `~/.ssh/config`
- Try manually: `ssh -L 9999:localhost:9999 user@server1.example.com -N`
- Check firewall on remote server

### API Returns 401 Unauthorized
```
{"success": false, "error": {"code": "UNAUTHORIZED"}}
```

**Solutions:**
- Check if `require_api_key: true` in remote config
- Add `api_key` to MCP instance config
- Restart MCP server after config change

### Connection Refused
```
Error: connect ECONNREFUSED 127.0.0.1:9999
```

**Solutions:**
- Verify REST API is running: `curl http://127.0.0.1:9999/api/v1/health`
- Check `config.yml`: `rest_api.enabled: true`
- Check daemon is running: `teleclaude status`
- Check logs: `tail -f /var/log/teleclaude.log`

### Port Already in Use
```
Error: Port 9999 already in use
```

**Solutions:**
- Check what's using port: `lsof -i :9999`
- Kill existing process or change port in config
- For MCP server: uses dynamic ports for tunnels, shouldn't conflict

---

**Status:** Ready for implementation
**Dependencies:** Phases 1-10 of main TODO must be completed first
**Estimated Time:** 2-3 weeks after core MVP complete
