# TeleClaude - Current TODOs

**Status**: Core daemon functional, 22/22 tests passing, multi-adapter complete
**Last Updated**: 2025-10-30

---

## P0: Critical UX Improvements

### Completion Notification System
**Priority**: P0 - Critical for long-running commands (Claude Code, builds, etc.)
**Reference**: Internal discussion on command completion detection
**Location**: `daemon.py` + adapter implementations

**Requirements:**
1. When user sends command to session, start async polling task
2. Wait 2 seconds (let process start up)
3. Poll tmux output every 1 second
4. Send/edit messages to adapter with new output
5. Detect 5 consecutive seconds of no new output
6. Send completion notification: "✅ Process completed (no output for 5s)"
7. Include last few lines of output in notification

**Key behaviors:**
- ALWAYS notify on silence, regardless of process exit status
- Universal pattern for all long-running commands
- Reset silence timer if new output appears
- Send notification only once per command
- Thread notification as reply to last output message

**Configuration** (add to `config.yml`):
```yaml
output:
  completion_notification:
    enabled: true
    startup_delay_seconds: 2
    poll_interval_seconds: 1
    silence_threshold_seconds: 5
    include_last_lines: 5
    # Future: skip_if_user_active: true (when adapter supports focus detection)
```

**Acceptance criteria:**
- [ ] User sends `npm run build` (20 second build)
- [ ] Output appears in Telegram after 2 seconds
- [ ] Updates every 1 second during build
- [ ] After build completes and 5 seconds pass
- [ ] Notification sent: "✅ Process completed (no output for 5s)"
- [ ] Notification is threaded reply to last output
- [ ] Works for all adapters (Telegram, REST)
- [ ] No duplicate notifications

**Test cases:**
- [ ] Long-running command with exit (npm build)
- [ ] Long-running command without exit (Claude Code)
- [ ] Command with sparse output (git clone large repo)
- [ ] Command that errors out (should still notify)
- [ ] Multiple concurrent sessions don't interfere

---

## P1: Must-Have Features

### REST API Completion
**Priority**: P1 - Needed for MCP server integration
**Reference**: `prds/rest-api-and-mcp.md`
**Current**: Health endpoint + session output endpoint exist

**Remaining endpoints** (see PRD for full specs):

#### Session Management
- [ ] `POST /api/v1/sessions` - Create session
  - Accepts: title, working_dir, terminal_size
  - Returns: session_id, tmux_session_name, status
  - Test: Create session via API, verify in Telegram
- [ ] `GET /api/v1/sessions` - List sessions
  - Query params: status, computer
  - Test: List active vs all sessions
- [ ] `GET /api/v1/sessions/{id}` - Get session info
  - Returns: Full session details
- [ ] `DELETE /api/v1/sessions/{id}` - Close session
  - Kills tmux, updates DB, notifies adapters

#### Command Execution
- [ ] `POST /api/v1/sessions/{id}/input` - Send command
  - Params: command, wait_for_completion (bool)
  - Test both async and sync modes
- [ ] `GET /api/v1/sessions/{id}/messages` - Get message range
  - Query: index, from, limit
- [ ] `GET /api/v1/sessions/{id}/history` - Command history
  - Query: limit (default 20)

#### File Operations
- [ ] `GET /api/v1/sessions/{id}/cwd` - Get current directory
- [ ] `POST /api/v1/sessions/{id}/cd` - Change directory
- [ ] `GET /api/v1/sessions/{id}/ls` - List directory
  - Query: path, details (bool)
- [ ] `GET /api/v1/sessions/{id}/files` - Read file
  - Query: path, lines, tail (bool)
- [ ] `POST /api/v1/sessions/{id}/files` - Upload file
  - Multipart form data

#### Control
- [ ] `POST /api/v1/sessions/{id}/resize` - Resize terminal
- [ ] `POST /api/v1/sessions/{id}/signal` - Send signal (SIGINT, etc.)
- [ ] `POST /api/v1/sessions/{id}/clear` - Clear screen

#### Status & Config
- [ ] `GET /api/v1/sessions/{id}/status` - Session status
- [ ] `GET /api/v1/status` - Daemon status
- [ ] `GET /api/v1/config/quick_paths` - List quick paths
- [ ] `GET /api/v1/config` - Get full config

**Middleware:**
- [ ] Authentication (optional X-TeleClaude-API-Key header)
- [ ] Rate limiting (slowapi: 30 req/min per IP)
- [ ] Audit logging to separate log file
- [ ] CORS for localhost only

**Testing:**
- [ ] Unit tests for all endpoints
- [ ] Integration test: Create session, send command, get output
- [ ] Test with/without API key
- [ ] Test rate limiting
- [ ] OpenAPI docs auto-generated at `/docs`

**Acceptance:**
- [ ] All endpoints functional and tested
- [ ] FastAPI auto-docs accessible at http://127.0.0.1:6666/docs
- [ ] Rate limiting prevents abuse
- [ ] Audit log captures all API calls

---

### File Upload Handler
**Priority**: P1 - Core feature for workflows
**Location**: `daemon.py` + adapters

- [ ] Document Telegram file upload behavior in README
- [ ] Add `/upload` command help text
- [ ] Test end-to-end: Upload via Telegram → File saved → Path sent back
- [ ] Test conflict resolution (duplicate filenames)
- [ ] Test file size limits

**Acceptance:**
- [ ] User uploads document in Telegram topic
- [ ] File saved to `~/telegram_uploads/` (or configured dir)
- [ ] Confirmation message with full path
- [ ] Duplicate files get timestamp suffix

---

## P2: Nice-to-Have Features

### Documentation
**Priority**: P2 - Important but not blocking

- [ ] Update `README.md`:
  - [ ] Complete feature list with examples
  - [ ] Installation guide (one-liner for macOS/Linux)
  - [ ] Configuration reference
  - [ ] All bot commands with screenshots
  - [ ] Troubleshooting section
  - [ ] Multi-computer setup guide
- [ ] Create `SETUP.md`:
  - [ ] Telegram bot creation steps
  - [ ] Supergroup setup
  - [ ] SSH key configuration for multi-computer
- [ ] Document multi-adapter architecture in `ARCHITECTURE.md`

**Acceptance:**
- [ ] New user can install and configure without asking questions
- [ ] All commands documented with examples
- [ ] Common issues have documented solutions

---

### AI Features (Deferred)

#### Title Generation
**Reference**: `prds/teleclaude.md` section on AI titles
**Dependencies**: Anthropic API integration

- [ ] Integrate Claude API for title generation
- [ ] Track first 5 commands per session
- [ ] Generate title after 5th command
- [ ] Update session title in DB
- [ ] Update Telegram topic title
- [ ] Update tmux session name
- [ ] Test with various command patterns
- [ ] Handle API failures gracefully (keep default title)

---

### Recording System (Deferred)
**Priority**: P2 - Advanced feature
**Reference**: `prds/teleclaude.md` recording section
**Dependencies**: asciinema, agg (GIF converter)

- [ ] Text recorder with rolling 20-minute window
- [ ] Video recorder (asciinema .cast files)
- [ ] GIF converter for video output
- [ ] `/send_text` command implementation
- [ ] `/send_video` command implementation
- [ ] Test recording rotation
- [ ] Test concatenation of multiple files
- [ ] Test GIF conversion quality/size

---

## P3: MCP Server Integration

**Priority**: P3 - Separate project after REST API complete
**Reference**: `prds/rest-api-and-mcp.md`
**Repository**: New repo `mcp-teleclaude` (Node.js/TypeScript)

### Phase 1: Core MCP Package
- [ ] Initialize Node.js/TypeScript project
- [ ] Add MCP SDK dependency: `@modelcontextprotocol/sdk`
- [ ] Create configuration loader (`~/.teleclaude/mcp-instances.json`)
- [ ] Implement SSH tunnel manager with on-demand initialization
- [ ] Implement REST API client wrapper
- [ ] Handle authentication (optional API keys)

### Phase 2: SSH Infrastructure
- [ ] SSH tunnel class with auto-retry
- [ ] Port allocation (dynamic local ports starting from 10000)
- [ ] Tunnel health checks
- [ ] Idle timeout (close tunnels after 5 min no use)
- [ ] SSH key validation on startup
- [ ] Test passwordless SSH works for all instances

### Phase 3: MCP Tools
Implement all tools from PRD (20+ tools):
- [ ] Session management (create, list, get, close)
- [ ] Command execution (send, get_output, get_message, history)
- [ ] Navigation (list_quick_paths, cd, ls, read_file, upload_file)
- [ ] Control (resize, cancel, rename)
- [ ] Status (get_status, get_daemon_status)

### Phase 4: Testing & Publishing
- [ ] Unit tests for tunnel management
- [ ] Integration tests with mock REST API
- [ ] End-to-end test with Claude Code
- [ ] CLI: `mcp-teleclaude --test` validates all instances
- [ ] Documentation (README, SETUP, API reference)
- [ ] Publish to npm as `mcp-teleclaude`

**Acceptance:**
- [ ] Claude Code can run commands on all configured servers
- [ ] SSH tunnels created on-demand
- [ ] All 20+ tools functional and tested
- [ ] Package installable via `npm install -g mcp-teleclaude`

---

## Development Notes

### Priority Legend
- **P0**: Critical - Breaks core UX, must fix immediately
- **P1**: High - Core features needed for 1.0 release
- **P2**: Medium - Important but not blocking
- **P3**: Low - Nice to have, future enhancement

### When to Move Items
- Mark P0 items as P1 once implemented and tested
- Move P3 to separate milestone after P1 complete
- Regularly review priorities based on user feedback

### Links to Specs
- Main design: `prds/teleclaude.md`
- REST API: `prds/rest-api-and-mcp.md`
- Adapter design: `prds/adapter-api-design.md`
- Future features: `prds/roadmap.md`

---

**Next Sprint Focus:**
1. ✅ P0: Completion notification system (highest ROI for UX)
2. REST API endpoints (needed for MCP server)
3. File upload documentation (quick win)
