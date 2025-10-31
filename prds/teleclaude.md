# TeleClaude - Telegram Terminal Bridge

## Overview
A pure terminal bridge that pipes Telegram messages to terminal stdin and terminal stdout back to Telegram. Enables remote terminal control from phone/tablet, with voice input and file uploads. Primary use case: running Claude Code CLI remotely.

**Core Philosophy**: This is NOT a custom AI bot. It's a dumb pipe between Telegram and a terminal. The intelligence comes from whatever you run in the terminal (Claude CLI, vim, htop, etc.).

## Requirements

### 1. Multiple Long-Running Terminal Sessions

**Architecture: Supergroup with Topics**
- One Telegram Supergroup for all TeleClaude operations
- **General topic** (`📋 General`): Bot commands (`/new-session`, `/list-sessions`, `/help`)
- **Session topics**: One topic per terminal session with format: `[{computer}] {ai-generated-title}`
  - Example: `[Mac] Claude debugging auth flow`
  - Example: `[Server1] Log monitoring production`
  - Topic title updated after first few commands via Claude API analysis

**Technical Implementation**:
- Use `tmux` for persistent terminal sessions
- Session naming: `{computer}-{ai-generated-title}` (e.g., `mac-debugging-auth`)
- Session registry stored in SQLite: (session_name, tmux_session_id, topic_id, computer_name)
- On daemon restart: scan existing tmux sessions and reconnect
- Session limits:
  - Cap at 100 total sessions (Telegram topic limit)
  - Warn user at 50 sessions
  - No idle timeout (costs nothing to keep open)

**Session Lifecycle**:
1. User: `/new-session` in General topic
2. Bot creates tmux session `{computer}-temp-{uuid}`
3. Bot creates Telegram topic with temporary title `[{computer}] New session...`
4. User sends commands to topic → routed to tmux stdin
5. After N commands, Claude API analyzes history and generates title
6. Bot renames topic and tmux session with AI-generated title
7. User: `/close-session` or closes topic manually → kill tmux session

### 2. File Upload Handling

**Implementation**:
- ALL file types supported (images, PDFs, code, videos, etc.)
- Files saved to `~/telegram_uploads/` with original filename
- Bot sends confirmation: `File saved: ~/telegram_uploads/screenshot.png`
- Files persist until manually deleted
- No automatic analysis - user must explicitly ask Claude to analyze

**Usage Pattern**:
```
[User uploads screenshot.png to topic]
Bot: "File saved: ~/telegram_uploads/screenshot.png"
User: "/check-upload screenshot.png" or just "claude" + ENTER
Claude CLI: [analyzes image via vision API]
```

**Considerations**:
- Telegram file size limits: 50MB for bots
- No automatic cleanup (user's responsibility)
- Filename conflicts: append timestamp if duplicate

### 3. Voice Mode

**Implementation**:
- Voice input only (no TTS output)
- Receive voice message → save to temp file
- Transcribe using OpenAI Whisper API (key in .env)
- Send transcription to terminal stdin + ENTER
- Bot shows transcription in Telegram for user confirmation

**Flow**:
```
User: [sends voice message]
Bot: "🎤 Transcribing..."
Bot: "Transcribed: ls -la ~/projects"
[sends "ls -la ~/projects\n" to terminal stdin]
Terminal: [outputs directory listing]
Bot: [streams output back to Telegram]
```

**Considerations**:
- Audio format: Telegram sends ogg/opus, convert to format Whisper expects
- Transcription errors: User sees transcription, can correct if wrong
- Language: Auto-detect or configure in .env
- Cost: ~$0.006 per minute of audio

## Technical Architecture

### Client-Agnostic Design

**Core Daemon (Platform-Independent)**
```
teleclaude/
├── core/
│   ├── session_manager.py    # Session lifecycle, SQLite storage
│   ├── terminal_bridge.py    # tmux interaction, I/O routing
│   ├── recorder.py            # Terminal recording (text + video)
│   ├── file_handler.py        # File upload/download management
│   ├── voice_handler.py       # Whisper transcription
│   └── title_generator.py     # Claude API for session titles
├── adapters/
│   ├── base_adapter.py        # Abstract base class
│   ├── telegram_adapter.py    # Telegram implementation
│   ├── whatsapp_adapter.py    # (Future)
│   └── slack_adapter.py       # (Future)
└── daemon.py                  # Main entry point
```

**Adapter Interface (base_adapter.py)**
```python
class BaseAdapter(ABC):
    @abstractmethod
    async def start(self):
        """Initialize adapter and connect to platform"""

    @abstractmethod
    async def send_message(self, session_id: str, text: str):
        """Send text message to session's channel"""

    @abstractmethod
    async def edit_message(self, session_id: str, message_id: str, text: str):
        """Edit existing message (for live updates)"""

    @abstractmethod
    async def send_file(self, session_id: str, file_path: str, caption: str):
        """Upload file to session's channel"""

    @abstractmethod
    async def create_channel(self, session_id: str, title: str) -> str:
        """Create new channel/topic/thread, return channel_id"""

    @abstractmethod
    async def update_channel_title(self, channel_id: str, title: str):
        """Update channel/topic title"""

    @abstractmethod
    async def set_channel_status(self, channel_id: str, status: str):
        """Update status indicator (🟢 active, ⏸️ idle, ❌ dead)"""

    @abstractmethod
    async def get_device_type(self, user_context) -> str:
        """Detect device type: mobile, tablet, desktop"""
```

**Session Storage (SQLite)**
```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,
    computer_name TEXT NOT NULL,
    title TEXT,
    tmux_session_name TEXT NOT NULL,
    adapter_type TEXT NOT NULL,  -- 'telegram', 'slack', etc.
    adapter_metadata JSON,       -- Platform-specific data
    status TEXT DEFAULT 'active', -- active, idle, disconnected
    created_at TIMESTAMP,
    last_activity TIMESTAMP,
    terminal_size TEXT DEFAULT '80x24',
    working_directory TEXT DEFAULT '~',
    UNIQUE(computer_name, tmux_session_name)
);
```

### Multi-Computer Support
- **One bot token** shared by all daemons
- Each daemon has local config with:
  - Computer name (e.g., "Mac", "Server1", "ProductionDB")
  - Bot token (shared)
  - User whitelist (Telegram user IDs)
  - Upload directory (default: `~/telegram_uploads`)
  - Default working directory (default: `~`)
  - Default shell (default: `$SHELL`)
- Each daemon creates topics prefixed with its computer name: `[{computer}] ...`

### Terminal Sizing (Dynamic)
- **Detection priority**:
  1. Try Telegram metadata (`update.effective_chat` for device hints)
  2. Fall back to default: 80x24
- **Size presets**:
  - `mobile`: 60 cols x 24 rows
  - `tablet`: 100 cols x 30 rows
  - `desktop`: 120 cols x 40 rows
- **User override**: `/resize small|medium|large` anytime
- Set in tmux: `tmux set-environment -t session COLUMNS 80; tmux set-environment -t session LINES 24`

### Terminal Recording (20-Minute Rolling Window)

**Implementation:**
- Use `tmux pipe-pane` to stream output to recorder
- Two parallel recordings:
  1. **Text log**: Plain text with ANSI codes stripped (for `/send-text`)
  2. **Video cast**: asciinema format (for `/send-video`)

**Rolling Window:**
- Rotate files every 60 seconds
- Keep last 20 files (20 minutes total)
- Auto-cleanup older files
- Files stored in `/tmp/teleclaude/recordings/{session_id}/`

**Commands:**
- `/send-text` - Upload last 20 minutes as .txt file
- `/send-video` - Convert last 20 minutes to GIF/video and upload
- `/send-text 5m` - Upload last 5 minutes only
- `/send-video 10m` - Upload last 10 minutes as video

**Technical Details:**
```bash
# Start recording on session creation
tmux pipe-pane -o -t session "tee >(teleclaude-record-text) | teleclaude-record-video"

# teleclaude-record-text: strips ANSI, writes to rotating text files
# teleclaude-record-video: pipes to asciinema rec, writes to rotating .cast files

# On /send-video:
# 1. Concatenate last N .cast files
# 2. Convert to GIF using agg or asciicast2gif
# 3. Upload to Telegram
```

### Output Streaming (Hybrid Mode)
- Poll tmux output every 1-2 seconds
- **First 5 seconds**: Edit same Telegram message in-place (clean, live updates)
- **After 5 seconds**: Send new message with continued output (preserves history)
- **Status indicators** (emoji in topic title):
  - 🟢 Active: output received in last 10 seconds
  - 🟡 Waiting: no output for 5-10 seconds, show "Awaiting response..."
  - 🟠 Slow: no output for 10-30 seconds
  - 🔴 Stalled: no output for 30+ seconds
  - ⏸️ Idle: no activity for 10+ minutes
  - ❌ Dead: tmux session died
- **Formatting**:
  - Strip ANSI color codes for text (Telegram doesn't support)
  - Preserve structure/indentation
  - Strip shell prompts (configurable: `strip_prompts: true` in config)
  - Wrap in code blocks: ` ```\n{output}\n``` `
  - Split at 4000 chars (Telegram limit 4096, leave margin)

### Large Output Handling
- **Detection**: More than 1000 lines or >100KB in single buffer
- **Truncation**: Keep last 100 lines (most recent)
- **Notification**: Show at top:
  ```
  ⚠️ Output truncated (2547 lines hidden)
  Last 100 lines shown. Use /send-text for full output.
  ```
- **Spam protection**: If output rate >1000 lines/sec, pause streaming and alert:
  ```
  🚨 High output rate detected! Streaming paused.
  Use /send-text or /send-video to retrieve.
  ```

### Telegram Message Rate Limiting
- Telegram limits: ~30 messages/sec, ~5 edits/sec per message
- Output polling every 1-2 seconds = well within limits
- Throttle topic creation: max 1 per second

### Error Handling & Retry
- **Telegram API failures**: Retry once (2 total attempts), then alert user
- **Whisper API failures**: Retry once, send error to user if fails
- **Unrecoverable errors**: Send alert to General topic
- **Daemon crash**: On restart, reconnect to existing tmux sessions and topics

## Technical Stack

- **Language**: Python 3.11+
- **Messaging**: `python-telegram-bot` library (v20+)
- **Terminal**: `tmux` for session persistence
- **Recording**:
  - `asciinema` for video cast recording
  - `agg` or `asciicast2gif` for GIF conversion
  - Custom text logger for plain text output
- **Voice**: OpenAI Whisper API
- **AI**: Claude API (Anthropic SDK, for session title generation only)
- **Storage**: SQLite3 for session/topic mappings
- **Logging**: `/var/log/teleclaude.log` (10MB rolling window)
- **Config**:
  - `.env` for secrets (bot token, Whisper key, Claude key, user IDs)
  - `config.yml` for settings (computer name, upload dir, shell, working dir, strip prompts)

### Python Dependencies
```
python-telegram-bot>=20.0
openai>=1.0.0
anthropic>=0.8.0
aiosqlite>=0.19.0
pyyaml>=6.0
python-dotenv>=1.0.0
```

### System Dependencies
- `tmux` (v3.0+) - Terminal multiplexer
- `ffmpeg` - Audio conversion for voice messages
- `asciinema` - Terminal recording
- `agg` - Asciinema to GIF converter
- Python 3.11+ with pip

### Deployment
- **Installation**: Make-based installation `make init` (or `make init ARGS=-y` for unattended) that:
  1. Detects OS (Linux/macOS)
  2. Checks Python version (3.11+ required)
  3. Installs system dependencies via package manager
  4. Creates Python virtual environment
  5. Installs Python packages
  6. Runs interactive setup wizard
  7. Creates systemd service (Linux) or launchd plist (macOS)
  8. Enables auto-start on boot
- **Setup wizard**: Interactive prompts for:
  - Computer name
  - Bot token (with @BotFather link)
  - Telegram user ID (with instructions to get it)
  - OpenAI API key (Whisper)
  - Claude API key (Anthropic)
  - Upload directory (default: ~/telegram_uploads)
  - Default working directory (default: ~)
  - Terminal size preferences
- **Log management**: 10MB rolling window at `/var/log/teleclaude.log`
- **Auto-start**: Daemon starts on boot via systemd/launchd
- **Updates**: `teleclaude update` - pulls latest, restarts daemon

## Architecture Diagram

```
┌─────────────────────────────────────────────────┐
│           Telegram Supergroup                   │
│                                                 │
│  📋 General Topic                               │
│     /new-session, /list-sessions, /help        │
│                                                 │
│  [Mac] Claude debugging auth flow               │
│     └─> tmux session: mac-debugging-auth       │
│                                                 │
│  [Server1] Log monitoring production            │
│     └─> tmux session: server1-log-monitoring   │
└─────────────────────────────────────────────────┘
                    ↕ Telegram Bot API
┌─────────────────────────────────────────────────┐
│         TeleClaude Daemon (per computer)        │
│  ┌───────────────────────────────────────────┐  │
│  │ Config: computer_name="Mac"               │  │
│  │         bot_token, user_whitelist         │  │
│  └───────────────────────────────────────────┘  │
│                                                 │
│  ┌─────────────┐  ┌──────────────┐            │
│  │   Router    │  │  Session Mgr │            │
│  │ Topic -> tmux│  │ SQLite DB    │            │
│  └─────────────┘  └──────────────┘            │
│                                                 │
│  ┌─────────────┐  ┌──────────────┐            │
│  │   Whisper   │  │ File Handler │            │
│  │   Handler   │  │ ~/uploads/   │            │
│  └─────────────┘  └──────────────┘            │
└─────────────────────────────────────────────────┘
                    ↕
┌─────────────────────────────────────────────────┐
│              tmux Sessions                      │
│                                                 │
│  mac-debugging-auth                             │
│    $ claude                                     │
│    Claude Code> ...                             │
│                                                 │
│  mac-log-monitoring                             │
│    $ tail -f /var/log/app.log                   │
└─────────────────────────────────────────────────┘
```

## Bot Commands

### Session Management
- `/new-session` - Create new terminal session (creates topic and tmux)
- `/list-sessions` - Show all active sessions across all computers
- `/close-session` - Close current topic's session (kill tmux)
- `/reconnect <session_name>` - Reconnect to dead/disconnected session
- `/rename <new_title>` - Manually override AI-generated title

### Output & Recording
- `/send-text [duration]` - Upload terminal output as .txt file (default: 20m)
- `/send-video [duration]` - Upload terminal recording as GIF/video (default: 20m)
- `/save-output` - Alias for `/send-text`

### Session Control
- `/cancel` - Send SIGINT (Ctrl+C) to current session
- `/resize small|medium|large` - Change terminal dimensions
- `/clear` - Clear terminal screen (send `clear` command)

### System Commands
- `/cleanup-zombies` - Clean up orphaned tmux sessions
- `/help` - Show available commands and usage guide
- `/check-upload <filename>` - Helper script for Claude to analyze uploaded files

## Key Features

### 1. Session Context in Messages
Output messages show context and command executed:
```
[Mac] debugging ~/projects/teleclaude
$ ls -la
total 48
drwxr-xr-x  12 maurice  staff   384 Oct 29 10:30 .
```

### 2. Login Shell Environment
- Sessions start with login shell (`$SHELL -l`)
- Full environment loaded (PATH, aliases, .bashrc/.zshrc)
- Configured working directory (default: `~`)

### 3. Smart Prompt Stripping
- Optionally strip common shell prompts (`$`, `%`, `>`)
- Configurable in `config.yml`: `strip_prompts: true`
- Saves screen space while preserving command visibility

### 4. Multi-line Input
- Telegram supports Shift+Enter for multi-line (desktop/mobile)
- Send entire block as-is to terminal stdin
- No special handling needed

### 5. Voice to Command
- Send voice message → auto-transcribe with Whisper
- Show transcription: `🎤 Transcribed: "list files in home directory"`
- Executes as if typed + ENTER
- User can correct if transcription wrong

### 6. File Upload Support
- Upload any file type (images, PDFs, code, videos)
- Saved to `~/telegram_uploads/` with timestamp
- Confirmation message with path
- Use with Claude: `/check-upload screenshot.png`

### 7. 20-Minute Recording Buffer
- Parallel text + video recording of all terminal output
- Rolling 20-minute window (auto-cleanup)
- `/send-text [duration]` - get plain text transcript
- `/send-video [duration]` - get GIF/video with colors & animations
- Perfect for sharing sessions or reviewing history

### 8. Dynamic Terminal Sizing
- Auto-detect device type from Telegram metadata
- Presets: mobile (60 cols), tablet (100 cols), desktop (120 cols)
- Override anytime: `/resize small|medium|large`
- Responsive to context

### 9. Real-time Status Indicators
- 🟢 Active: receiving output
- 🟡 Waiting: 5-10 sec no output, show "Awaiting response..."
- 🟠 Slow: 10-30 sec no output
- 🔴 Stalled: 30+ sec no output
- ⏸️ Idle: 10+ min no activity
- ❌ Dead: tmux session died

### 10. Smart Output Truncation
- Auto-detect large outputs (>1000 lines or >100KB)
- Show last 100 lines + truncation notice
- Spam protection: pause if >1000 lines/sec
- Use `/send-text` for full output

### 11. Session Persistence & Recovery
- tmux sessions survive daemon restarts
- On daemon start: auto-reconnect to existing sessions
- On computer reboot: detect dead sessions, mark as [DISCONNECTED]
- `/reconnect <name>` to recreate with same topic

### 12. AI-Generated Session Titles
- After first few commands, Claude API analyzes context
- Generates meaningful title: "debugging auth flow" or "monitoring production logs"
- Auto-updates topic and tmux session name
- User can override: `/rename <new-title>`

### 13. Multi-Computer Management
- Single bot token across all computers
- Sessions prefixed: `[Mac] ...`, `[Server1] ...`
- `/list-sessions` shows all computers at a glance
- Seamless switching between computers

### 14. Ctrl+C / Cancel
- `/cancel` sends SIGINT to current session
- Interrupts long-running commands
- Essential for remote terminal control

### 15. Zombie Cleanup
- `/cleanup-zombies` finds orphaned tmux sessions
- Offers to kill or reconnect
- Keeps system clean after crashes/reboots

---

## Advanced Features (Post-MVP)

### Quick Directory Navigation

Typing paths on mobile is painful. Quick CD makes navigation one-tap easy.

**Features:**
- `/cd` command shows inline keyboard with preset paths
- Configure common paths in `config.yml`: Projects, Logs, Config, etc.
- One-tap navigation from Telegram
- Manual path input still supported: `/cd /custom/path`
- Current working directory shown in all messages

**Configuration:**
```yaml
quick_paths:
  - name: "Projects"
    path: "~/projects"
  - name: "Logs"
    path: "/var/log"
  - name: "Temp"
    path: "/tmp"
  - name: "Config"
    path: "~/.config"
```

**Usage:**
```
User: /cd
Bot: [Shows buttons: Projects | Logs | Temp | Config | Other...]

User: [Taps "Logs"]
Bot: Changed directory: /var/log
```

### Live Config Reload

Config changes auto-detected and applied without daemon restart.

**Features:**
- Daemon watches `config.yml` for changes (using `watchdog` library)
- Hot reload for safe changes (terminal size, quick paths, prompts, etc.)
- Notifications sent to all active sessions when config updates
- Warning if restart required (bot token, adapter settings)
- Config validation before reload

**Notification Example:**
```
⚙️ Config updated on [Mac]
├─ Terminal size: 80x24 → 120x40
├─ Quick paths: Added "Deploy" → /opt/deploy
└─ Strip prompts: true → false

Daemon restart required: No
```

**Edge Cases Handled:**
- Invalid YAML → keep old config, notify error
- Conflicting changes → last write wins
- Restart required → show restart command

### REST API & MCP Integration

**Ultimate power-up:** Claude Code can now orchestrate terminal operations across multiple computers programmatically.

**Architecture:**
```
Claude Code (local) → MCP Protocol → TeleClaude MCP Server
                                     ↓ SSH Tunnels
                        [Mac]     [Server1]     [ProdDB]
                        REST API   REST API     REST API
```

**Key Features:**
- REST API on each TeleClaude daemon (binds to localhost only)
- SSH tunnels for secure communication (no HTTPS needed)
- MCP server manages tunnels on-demand (lazy initialization)
- Comprehensive tools: create sessions, run commands, get output, file ops, recordings
- Multi-server orchestration: run commands in parallel, aggregate results

**Use Cases:**

**1. Single Server Command:**
```
User: "Check if nginx is running on server1"
Claude: [Creates session, runs systemctl status, returns result]
```

**2. Multi-Server Log Search:**
```
User: "Find error 'timeout' in logs on all servers"
Claude: [Searches all servers in parallel, aggregates results]
```

**3. Deployment Automation:**
```
User: "Deploy app to production"
Claude: [Creates session, git pull, npm install, build, restart, health check]
```

**4. Monitoring & Recording:**
```
User: "Show me video of the failed build"
Claude: [Gets 20-minute recording, analyzes, suggests fix]
```

**Security:**
- REST API never exposed to internet (localhost only)
- SSH tunnels with key auth (REQUIRED)
- API key optional (default: disabled for trusted networks)
- Rate limiting and audit logging
- See `prds/rest-api-and-mcp.md` for complete specification

**Future Enhancement:**
- Multi-user session sharing: invite others to watch/interact with session
- Perfect for pair programming, debugging help, or demos

## Security

- **Authentication**: Whitelist Telegram user IDs in .env
- **No command restrictions**: God mode - full terminal access
- **No auto-redaction**: User responsible for not exposing secrets
- **Rate limiting**: Built-in throttling to avoid Telegram API bans
- **Bot token**: Keep secret, rotate periodically

## Missing Use Cases & Potential Pitfalls

### Edge Cases Handled

1. **Interactive terminal apps** (vim, htop, nano):
   - These use ANSI cursor positioning and will break
   - User should avoid or use workarounds (`vim -e`, `cat` instead of `less`)
   - Consider adding warning when detecting interactive app

2. **Large file uploads** (videos, big PDFs):
   - Telegram supports up to 50MB
   - Download is async, show progress?
   - Or just simple "Downloading..." then "Saved"

3. **Binary output**:
   - Terminal outputs binary (cat image.png)
   - Detect non-UTF8 and truncate with warning
   - Show: `[Binary output detected, truncated]`

4. **Long-running commands** (npm install, docker build):
   - Hybrid mode handles this: streams updates every 2 seconds
   - Can take minutes/hours - output continues in new messages

5. **Empty output**:
   - Command returns nothing (e.g., `cd /tmp`)
   - Show: `✓ Command completed (no output)`

6. **Session title conflicts**:
   - Two sessions get same AI-generated title
   - Append counter: `[Mac] debugging (1)`, `[Mac] debugging (2)`

7. **Telegram message limits** (4096 chars):
   - Long output split into multiple messages
   - Each with "...continued" indicator

8. **UTF-8 encoding issues**:
   - Terminal has weird characters or emoji
   - Handle with errors='replace' or errors='ignore'

9. **tmux capture race conditions**:
   - Use `tmux pipe-pane` to log to file, tail that file
   - More reliable than `tmux capture-pane`

10. **Voice transcription errors**:
    - Show transcription to user for visual confirmation
    - If wrong, user can type correction

### Operational Concerns

1. **Daemon updates**:
   - Graceful restart: stop accepting new commands, finish in-flight
   - tmux sessions persist through daemon restart
   - Topics reconnect automatically

2. **Config changes**:
   - Changing computer name requires manual topic renaming
   - Or: provide `/update-config` that renames all topics

3. **Zombie sessions**:
   - Daemon crash leaves tmux running
   - On restart: reconnect or prompt user to clean up
   - Provide `/cleanup-zombies` command

4. **Telegram supergroup migration**:
   - Group ID changes on migration
   - Store group ID in DB, update on migration event
   - Bot must be admin to receive migration events

5. **Bot token rotation**:
   - Update .env on all machines
   - Restart all daemons
   - Document procedure

### UX Enhancements (Future)

1. `/save-output` - Send last N lines as .txt file (easier to copy on mobile)
2. `/history` - Show bash command history
3. `/alert "keyword"` - Notify when keyword appears in output
4. Session snapshots/bookmarks
5. Output filtering: `/grep "error"` to filter live output
6. Command confirmation for destructive ops (optional, disabled by default)

## Setup Steps (Detailed in todo.md)

1. Create Telegram bot via @BotFather
2. Create Telegram Supergroup
3. Enable Topics in supergroup settings
4. Add bot to supergroup with admin rights
5. Get supergroup ID and topic IDs
6. Configure .env with bot token, keys, user ID
7. Configure config.yml with computer name
8. Run install script
9. Start daemon
10. Test `/new-session` command

## References

- Telegram Bot API: https://core.telegram.org/bots/api
- python-telegram-bot: https://docs.python-telegram-bot.org/
- tmux manual: https://man.openbsd.org/tmux
- OpenAI Whisper API: https://platform.openai.com/docs/guides/speech-to-text
