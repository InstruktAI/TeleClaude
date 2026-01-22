# TeleClaude

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-GPL--3.0-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-331%20passed-brightgreen.svg)](tests/)
[![Coverage](https://img.shields.io/badge/coverage-85%25-brightgreen.svg)](coverage/html/index.html)
[![Code Style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Type Checking](https://img.shields.io/badge/type%20checking-mypy-blue.svg)](http://mypy-lang.org/)

Control your terminal sessions remotely via Telegram. Run commands, monitor outputs, and manage multiple computers from your phone, tablet, or desktop.

[![TeleClaude](./assets/TeleClaude.png)](./assets/TeleClaude.png)

## What is TeleClaude?

TeleClaude is a terminal and agent orchestration layer. It doesn’t run its own model; it coordinates external CLIs (Claude, Codex, Gemini, shell tools) and exposes MCP tools for automation across computers and adapters.

**Key Features:**

- 🖥️ **Multiple persistent terminal sessions** - Each session runs in tmux and survives daemon restarts
- 📱 **Remote control from anywhere** - Send commands from Telegram, receive live output
- 🏢 **Multi-computer support** - Manage Mac, servers, and other machines from one Telegram group
- 🤖 **AI-to-AI communication** - MCP server enables Agents on different computers to collaborate
- 🔌 **Multi-adapter architecture** - Supports Telegram and Redis adapters for cross-computer messaging
- 📋 **Organized with Topics** - Each session gets its own Telegram topic for clean organization
- 🔄 **Live output streaming** - See command output in real-time with smart editing (dual-mode: human vs AI)
- 🎤 **Voice input** - Speak commands, auto-transcribed with Whisper
- 📎 **File uploads** - Send documents and photos directly to Agents for analysis

## Quick Start

### Prerequisites

- Python 3.11 or higher
- tmux 3.0 or higher
- `uv` (Python package manager; must be on `PATH`)
- Telegram account
- A Telegram bot token (from [@BotFather](https://t.me/botfather))

**Install `uv`:**

```bash
# macOS
brew install uv

# Debian/Ubuntu (if your distro packages it)
sudo apt-get update && sudo apt-get install uv
```

`make install` (and `make init`) will attempt to install `uv` for you (brew on macOS, apt-get on Linux) if it's missing.

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

**Note for multi-computer deployments:** For automated git operations (Redis deployments), you must configure the daemon as a **user service** with SSH agent access. See [SSH Agent Configuration](#ssh-agent-configuration-for-deployments) section below.

The service automatically:

- Starts on system boot
- Restarts if it crashes

**Development mode** (run in foreground):

```bash
make stop      # Stop service first
make dev       # Run with Ctrl+C to stop
make start     # Re-enable service when done
```

## Definition of Done

TeleClaude follows the global software-development Definition of Done. See
`agents/docs/software-development/standards/definition-of-done.md`.

## Docs + Agent Artifacts Auto-Sync

Run `telec /init` from a project root to build docs indexes, distribute agent artifacts, and
install an OS watcher that re-runs the sync on changes to `.agents`, `docs`, `agents/docs`,
or `teleclaude.yml`.

## Usage

### Creating a Session

In your Telegram supergroup's **General** topic, send:

```
/new-session
```

A new topic will be created with the format `[ComputerName] Untitled...`. All messages sent to this topic will be executed as terminal commands.

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

**AI-to-AI sessions** - Enable Agent instances to collaborate (see next section).

For detailed multi-computer setup with MCP server, see [docs/multi-computer-setup.md](docs/multi-computer-setup.md).

### SSH Agent Configuration for Deployments

**Critical for automated git operations** (like Redis-based deployments):

The daemon needs access to your SSH agent to perform git operations (pulls, pushes). On Linux systems, configure as follows:

**1. Use keychain for persistent SSH agent:**

```bash
# Install keychain
sudo apt-get install keychain  # Debian/Ubuntu
sudo dnf install keychain      # Fedora/RHEL

# Add to ~/.zshrc (or ~/.bashrc):
eval $(keychain --eval --quiet --agents ssh id_ed25519)

# Remove oh-my-zsh ssh-agent plugin if present:
# Change: plugins=(git ssh-agent)
# To: plugins=(git)
```

**2. Run as user service (not system service):**

The daemon must run as a **user systemd service** to access your SSH agent:

```bash
# Create user service directory
mkdir -p ~/.config/systemd/user/

# Create service file: ~/.config/systemd/user/teleclaude.service
[Unit]
Description=TeleClaude Terminal Bridge Daemon
After=default.target

[Service]
Type=simple
WorkingDirectory=%h/apps/TeleClaude
ExecStart=%h/apps/TeleClaude/bin/teleclaude-wrapper.sh
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
```

**3. Create wrapper script:**

```bash
# Create: ~/apps/TeleClaude/bin/teleclaude-wrapper.sh
#!/bin/bash
# Source keychain environment (auto-updates when keychain restarts)
if [ -f ~/.keychain/$(hostname)-sh ]; then
    source ~/.keychain/$(hostname)-sh
fi
exec /path/to/TeleClaude/.venv/bin/python -m teleclaude.daemon
```

```bash
chmod +x ~/apps/TeleClaude/bin/teleclaude-wrapper.sh
```

**4. Enable and start user service:**

```bash
# Enable user service
systemctl --user enable teleclaude.service
systemctl --user start teleclaude.service

# Enable linger (keeps service running after logout)
sudo loginctl enable-linger $USER

# Check status
systemctl --user status teleclaude
```

**5. Initialize SSH key after reboot:**

After each system reboot, SSH in once to unlock your key:

```bash
ssh user@your-machine
# Enter SSH key passphrase when prompted
# Keychain will persist the unlocked key until next reboot
```

**Why this is needed:**

- Keychain maintains a persistent SSH agent with your unlocked keys
- The wrapper sources `~/.keychain/$(hostname)-sh` which contains the current agent socket path
- No hardcoded ephemeral socket paths - keychain updates the file automatically
- User services inherit your user session's environment (including SSH agent)

**Verification:**

```bash
# Check daemon has access to SSH agent
ps aux | grep teleclaude.daemon | awk '{print $2}' | xargs -I {} sudo cat /proc/{}/environ | tr '\0' '\n' | grep SSH

# Should show: SSH_AUTH_SOCK=/tmp/ssh-xxxxx/agent.xxxxx
```

### AI-to-AI Communication (MCP Server)

TeleClaude includes a **Model Context Protocol (MCP) server** that enables Agent instances on different computers to communicate with each other. Redis transport is required for cross-computer orchestration.

**What it enables:**

- Agents on your **macbook** can ask Agents on your **deployment server** to deploy artifacts
- Agents on your **server** can ask Agents on your **laptop** to run tests
- Multiple computers can collaborate on complex tasks automatically

**Quick Setup:**

1. **Install TeleClaude on each computer** with unique bot tokens
2. **Add all bots to the same Telegram supergroup**
3. **Configure Agents** to use the TeleClaude MCP server:

   `make init` configures this automatically. For manual setup, add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "teleclaude": {
      "type": "stdio",
      "command": "socat",
      "args": ["-", "UNIX-CONNECT:/tmp/teleclaude.sock"]
    }
  }
}
```

**Available MCP Tools:**

- `teleclaude__list_computers` - List all online computers in the network
- `teleclaude__list_projects` - List available project directories on a computer
- `teleclaude__list_sessions` - List active AI-to-AI sessions
- `teleclaude__start_session` - Start AI-to-AI session with remote computer
- `teleclaude__send_message` - Send message to a session
- `teleclaude__get_session_data` - Get session transcript data
- `teleclaude__stop_notifications` - Unsubscribe from session events without ending it
- `teleclaude__end_session` - Gracefully terminate a session
- `teleclaude__deploy` - Deploy latest code to remote computers (optional list; default all remotes)
- `teleclaude__send_file` - Send a file to a session

**Example Usage:**

```bash
# In Agent on macbook:
> Use teleclaude to ask the workstation computer to check /var/log/nginx/error.log

# Agent will:
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
│  Agent (macbook)   │      │  Agent (server1)   │
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

### Debugging

1. Check status: `make status`
2. Restart daemon: `make restart`
3. Check daemon logs: `instrukt-ai-logs teleclaude --since 10m`

Log verbosity:

- `TELECLAUDE_LOG_LEVEL` controls TeleClaude logs.
- `TELECLAUDE_THIRD_PARTY_LOG_LEVEL` controls third-party baseline verbosity.
- `TELECLAUDE_THIRD_PARTY_LOGGERS` selectively enables third-party logger prefixes.

## Contributing

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
  - ✅ Notifications between Agent instances
  - ✅ Concurrent session support (15+ tested)
  - ✅ Multi-hop communication (Comp1 → Comp2 → Comp3)
- ✅ Voice input with Whisper transcription
- ✅ File upload handling via MCP (send files to Telegram from daemon)

**Planned:**

- 🔲 AI-generated session titles
- 🔲 REST API endpoints for output access
- 🔲 Session sharing for pair programming
- 🔲 Output filtering and alerts
- 🔲 Session templates and presets

## Documentation

- **[Architecture Reference](docs/architecture.md)** - System design and component layers
- **[MCP Architecture](docs/mcp-architecture.md)** - Resilient MCP server with zero-downtime restarts
- **[Protocol Architecture Guide](docs/protocol-architecture.md)** - Cross-computer orchestration patterns
- **[Multi-Computer Setup](docs/multi-computer-setup.md)** - AI-to-AI communication setup
- **[Troubleshooting Guide](docs/troubleshooting.md)** - Common issues and solutions
- **[Refactoring Summary](docs/REFACTORING_SUMMARY.md)** - Recent architectural improvements

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
