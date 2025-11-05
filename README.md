# TeleClaude

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-GPL--3.0-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-331%20passed-brightgreen.svg)](tests/)
[![Coverage](https://img.shields.io/badge/coverage-85%25-brightgreen.svg)](coverage/html/index.html)
[![Code Style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Type Checking](https://img.shields.io/badge/type%20checking-mypy-blue.svg)](http://mypy-lang.org/)

Control your terminal sessions remotely via Telegram. Run commands, monitor outputs, and manage multiple computers from your phone, tablet, or desktop.

## What is TeleClaude?

TeleClaude is a pure terminal bridge - a "dumb pipe" between Telegram and your terminal. It's **NOT** a custom AI bot. The intelligence comes from whatever you run in the terminal (Claude CLI, vim, htop, or any other tool).

**Key Features:**

- 🖥️ **Multiple persistent terminal sessions** - Each session runs in tmux and survives daemon restarts
- 📱 **Remote control from anywhere** - Send commands from Telegram, receive live output
- 🏢 **Multi-computer support** - Manage Mac, servers, and other machines from one Telegram group
- 🤖 **AI-to-AI communication** - MCP server enables Claude Code on different computers to collaborate via Telegram
- 📋 **Organized with Topics** - Each session gets its own Telegram topic for clean organization
- 🔄 **Live output streaming** - See command output in real-time with smart editing (dual-mode: human vs AI)
- 🎤 **Voice input** - Speak commands, auto-transcribed with Whisper
- 📁 **File uploads** (planned) - Upload files directly to your terminal session

## Quick Start

### Prerequisites

- Python 3.11 or higher
- tmux 3.0 or higher
- Telegram account
- A Telegram bot token (from [@BotFather](https://t.me/botfather))

### Installation

```bash
# Clone the repository
git clone https://github.com/morriz/teleclaude.git
cd teleclaude

# Install dependencies
make install

# Run installation wizard (interactive)
make init

# Or run in unattended mode
# (CI: env vars already set; Locally: source .env first if needed)
make init ARGS=-y
```

The installation wizard will:

- Detect your OS (macOS or Linux)
- Check Python 3.11+ and tmux are installed
- Create virtual environment and install dependencies
- Set up `.env` and `config.yml` files
- Install and start the system service (launchd/systemd)

### Configuration

The `make init` wizard will prompt you for these values:

1. **Create a Telegram Bot:**

   - Message [@BotFather](https://t.me/botfather) on Telegram
   - Send `/newbot` and follow instructions
   - Copy the bot token

2. **Create a Telegram Supergroup:**

   - Create a new group in Telegram
   - Convert it to Supergroup (Group Settings > Group Type)
   - Enable Topics (Group Settings > Topics)
   - Add your bot to the group with admin rights

3. **Get your Telegram User ID:**

   - Message [@userinfobot](https://t.me/userinfobot)
   - Copy your user ID

4. **Get the Supergroup ID:**

   - Add your bot to the supergroup
   - Send a message in the group
   - Visit: `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates`
   - Look for `"chat":{"id":-1234567890...}` (negative number)

5. **Optional: OpenAI API Key** (for voice transcription)

The wizard will create `.env` and `config.yml` files with your settings.

### Running

After `make init`, the daemon runs as a system service:

**macOS:**

```bash
make status    # Check if running
make restart   # Restart daemon
make stop      # Stop service
make start     # Start service
```

**Linux:**

```bash
make status    # Check if running
make restart   # Restart daemon
make stop      # Stop service
make start     # Start service
```

The service automatically:

- Starts on system boot
- Restarts if it crashes
- Logs to `/var/log/teleclaude.log`

**Development mode** (run in foreground):

```bash
make stop      # Stop service first
make dev       # Run with Ctrl+C to stop
make start     # Re-enable service when done
```

## Usage

### Creating a Session

In your Telegram supergroup's **General** topic, send:

```
/new-session
```

A new topic will be created with the format `[ComputerName] New session...`. All messages sent to this topic will be executed as terminal commands.

### Sending Commands

Simply type your command in the session topic:

```
ls -la
```

The output will appear in the same topic. For long-running commands, output updates in real-time.

### Available Commands

**Session Management:**

- `/new-session` - Create a new terminal session
- `/list-sessions` - Show all active sessions
- `/close-session` - Close current session (in session topic)

**Session Control:**

- `/cancel` - Send Ctrl+C (SIGINT) to interrupt current command
- `/cancel2x` - Send Ctrl+C twice (for stubborn programs)
- `/resize small|medium|large|WxH` - Change terminal dimensions
- `/clear` - Clear terminal screen

**System:**

- `/help` - Show available commands

### Multi-line Commands

Telegram supports multi-line input with Shift+Enter:

```bash
for file in *.txt; do
  echo "Processing $file"
  cat "$file" | wc -l
done
```

### Managing Multiple Computers

Install TeleClaude on multiple computers - each with a **unique bot token** and **computer name**. All bots join the same Telegram supergroup.

**Human sessions** - All sessions appear with clear prefixes:

- `[Mac] Claude debugging auth flow`
- `[Server1] Log monitoring production`
- `[ProdDB] Database backup`

Use `/list-sessions` to see all sessions across all computers.

**AI-to-AI sessions** - Enable Claude Code instances to collaborate (see next section).

For detailed multi-computer setup with MCP server, see [docs/multi-computer-setup.md](docs/multi-computer-setup.md).

### AI-to-AI Communication (MCP Server)

TeleClaude includes a **Model Context Protocol (MCP) server** that enables Claude Code instances on different computers to communicate with each other using Telegram as a distributed message bus.

**What it enables:**

- Claude Code on your **macbook** can ask Claude Code on your **workstation** to check logs
- Claude Code on your **server** can ask Claude Code on your **laptop** to run tests
- Multiple computers can collaborate on complex tasks automatically

**Quick Setup:**

1. **Install TeleClaude on each computer** with unique bot tokens
2. **Add all bots to the same Telegram supergroup**
3. **Configure Claude Code** to use the TeleClaude MCP server:

```json
// ~/.config/claude/config.json
{
  "mcpServers": {
    "teleclaude": {
      "command": "/path/to/teleclaude/.venv/bin/python",
      "args": ["-m", "teleclaude.mcp_server"],
      "env": {
        "TELECLAUDE_CONFIG": "/path/to/teleclaude/config.yml",
        "TELECLAUDE_ENV": "/path/to/teleclaude/.env"
      }
    }
  }
}
```

**Available MCP Tools:**

- `teleclaude__list_computers` - List all online computers in the network
- `teleclaude__start_session` - Start AI-to-AI session with remote computer
- `teleclaude__list_sessions` - List active AI-to-AI sessions
- `teleclaude__send` - Send command to remote computer and stream response

**Example Usage:**

```bash
# In Claude Code on macbook:
> Use teleclaude to ask the workstation computer to check /var/log/nginx/error.log

# Claude Code will:
# 1. List available computers (finds "workstation")
# 2. Start session with workstation
# 3. Send command: tail -100 /var/log/nginx/error.log
# 4. Stream response back in real-time
```

**For detailed setup instructions, see [docs/multi-computer-setup.md](docs/multi-computer-setup.md)**

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│               Telegram Supergroup (Message Bus)              │
│  ┌──────────────────┐  ┌───────────────────────────────┐    │
│  │  📋 General      │  │  🤖 Online Now (Heartbeat)    │    │
│  │  /new-session    │  │  macbook - last seen 5s ago   │    │
│  └──────────────────┘  │  server1 - last seen 8s ago   │    │
│                        └───────────────────────────────┘    │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  [Mac] Session 1 (Human)                             │   │
│  │  ↔ tmux: mac-session-abc123                          │   │
│  └──────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  $macbook > $server1 - Check logs (AI-to-AI)        │   │
│  │  ↔ tmux: macbook-ai-789 & server1-ai-012            │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                      ↕ Telegram Bot API
┌──────────────────────────┐      ┌──────────────────────────┐
│  TeleClaude (macbook)    │      │  TeleClaude (server1)    │
│  ┌────────────────────┐  │      │  ┌────────────────────┐  │
│  │ MCP Server (stdio) │←─┼──────┼→ │ MCP Server (stdio) │  │
│  └────────────────────┘  │      │  └────────────────────┘  │
│  ┌────────────────────┐  │      │  ┌────────────────────┐  │
│  │ Daemon Core        │  │      │  │ Daemon Core        │  │
│  │ • Session Manager  │  │      │  │ • Session Manager  │  │
│  │ • Computer Registry│  │      │  │ • Computer Registry│  │
│  │ • Terminal Bridge  │  │      │  │ • Terminal Bridge  │  │
│  │ • Telegram Adapter │  │      │  │ • Telegram Adapter │  │
│  └────────────────────┘  │      │  └────────────────────┘  │
└──────────────────────────┘      └──────────────────────────┘
          ↕                                   ↕
┌──────────────────────────┐      ┌──────────────────────────┐
│  tmux sessions           │      │  tmux sessions           │
│  mac-session-abc123      │      │  server1-session-def456  │
│  macbook-ai-789          │      │  server1-ai-012          │
└──────────────────────────┘      └──────────────────────────┘
          ↕                                   ↕
┌──────────────────────────┐      ┌──────────────────────────┐
│  Claude Code (macbook)   │      │  Claude Code (server1)   │
│  Uses MCP tools to send  │      │  Executes commands and   │
│  commands to server1     │      │  streams output back     │
└──────────────────────────┘      └──────────────────────────┘
```

## Troubleshooting

### Daemon won't start - "Another daemon instance is already running"

```bash
# Check if process is actually running
ps aux | grep teleclaude

# If no process found, remove stale PID file
rm teleclaude.pid

# Try starting again
make start
```

### Bot doesn't respond to commands

1. Check bot is admin in supergroup (required for topic management)
2. Verify your Telegram user ID is in `TELEGRAM_USER_IDS` whitelist
3. Check daemon logs: `tail -f /var/log/teleclaude.log`
4. Verify bot token is correct in `.env`

### tmux sessions not being created

```bash
# Check if tmux is installed
which tmux
tmux -V  # Should be 3.0+

# Test tmux manually
tmux new-session -d -s test-session
tmux list-sessions
tmux kill-session -t test-session
```

### Output not appearing in Telegram

1. Check if command produces output: `echo "test"` should return `test`
2. Verify terminal size isn't too small (default: 80x24)
3. Try `/resize large` in session topic
4. Check daemon logs for errors

### Sessions lost after reboot

tmux sessions don't survive system reboots. After restart:

1. Start the TeleClaude daemon
2. Old topic threads will show as disconnected
3. Create new sessions with `/new-session`

## Development

**Quick Start:** Run `make help` for all available commands.

```bash
make install      # Install dependencies
make init         # Run installation wizard (or ARGS=-y for unattended)
make format       # Format code
make lint         # Run linting checks
make test-unit    # Run unit tests
make test-e2e     # Run integration tests
make test-all     # Run all tests
make dev          # Run daemon in foreground
make clean        # Clean generated files
make status       # Check daemon status
make restart      # Restart daemon
```

See developer documentation:

- **[CLAUDE.md](CLAUDE.md)** - Development workflow, coding rules, testing guidelines
- **[docs/architecture.md](docs/architecture.md)** - Technical architecture including MCP server design
- **[docs/multi-computer-setup.md](docs/multi-computer-setup.md)** - Multi-computer deployment guide
- **[docs/troubleshooting.md](docs/troubleshooting.md)** - Common issues and solutions

## Security

- **Authentication**: Only whitelisted Telegram user IDs can use the bot
- **Full terminal access**: Users have complete control - NO command restrictions
- **Secrets**: Keep `.env` file secure, never commit to git
- **Bot token**: Rotate periodically, keep private
- **Network**: Daemon only connects to Telegram API, no incoming connections

## Roadmap

**Implemented:**

- ✅ Multiple persistent terminal sessions via tmux
- ✅ Telegram supergroup with topic-based organization
- ✅ Multi-computer support with unique bot tokens per computer
- ✅ Live output streaming with dual-mode architecture (human vs AI)
- ✅ Session lifecycle management
- ✅ Basic commands (/new-session, /cancel, /resize)
- ✅ **MCP server for AI-to-AI communication**
  - ✅ Computer discovery via heartbeat mechanism
  - ✅ Real-time streaming between Claude Code instances
  - ✅ Concurrent session support (15+ tested)
  - ✅ Multi-hop communication (Comp1 → Comp2 → Comp3)
- ✅ Voice input with Whisper transcription

**Planned:**

- 🔲 File upload handling
- 🔲 AI-generated session titles
- 🔲 REST API endpoints for output access
- 🔲 Session sharing for pair programming
- 🔲 Output filtering and alerts
- 🔲 Session templates and presets

## License

GPL-3.0-only

## Contributing

Contributions welcome! Please:

1. Fork the repository
2. Create a feature branch
3. Follow code style (run `./bin/format.sh` and `./bin/lint.sh`)
4. Write tests for new features
5. Submit a pull request

## Support

- **Issues**: [GitHub Issues](https://github.com/morriz/teleclaude/issues)
- **Discussions**: [GitHub Discussions](https://github.com/morriz/teleclaude/discussions)
- **Email**: maurice@instrukt.ai

## Acknowledgments

Built with:

- [python-telegram-bot](https://python-telegram-bot.org/) - Telegram Bot API wrapper
- [tmux](https://github.com/tmux/tmux) - Terminal multiplexer
- [aiosqlite](https://aiosqlite.omnilib.dev/) - Async SQLite
