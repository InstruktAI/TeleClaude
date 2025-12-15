# Multi-Computer Setup Guide

This guide explains how to set up TeleClaude for AI-to-AI communication across multiple computers using the MCP (Model Context Protocol) server.

## Overview

**What is AI-to-AI communication?**

TeleClaude enables Claude Code running on different computers to communicate with each other via Telegram as a distributed message bus. For example:

- Claude Code on your **macbook** can ask Claude Code on your **workstation** to check logs
- Claude Code on your **server** can ask Claude Code on your **laptop** to run tests
- Multiple computers can collaborate on complex tasks

**How it works:**

1. Each computer runs its own TeleClaude daemon with a unique bot token
2. All bots join the same Telegram supergroup
3. Computers discover each other via heartbeat messages
4. Claude Code uses MCP tools to send commands and receive streaming responses

---

## Prerequisites

Before setting up multi-computer communication, ensure:

- ✅ TeleClaude installed on each computer (see main README.md)
- ✅ Each computer has a **unique Telegram bot token** (create via @BotFather)
- ✅ All bots are added to the **same Telegram supergroup**
- ✅ Supergroup has **Topics enabled** (Settings → Group Type → Forum)
- ✅ Claude Code installed on computers that will receive commands

---

## Step 1: Create Telegram Bots

You need **one bot per computer**. Each bot must have a unique token.

### Create Bots via @BotFather

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` command
3. Follow prompts to create a bot:
   - **Bot name**: `TeleClaude Macbook` (human-readable, can contain spaces)
   - **Bot username**: `teleclaude_macbook_bot` (unique, lowercase, ends with `_bot`)
4. Save the bot token (looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)
5. Repeat for each computer:
   - Computer 2: `teleclaude_workstation_bot`
   - Computer 3: `teleclaude_server_bot`
   - Computer 4: `teleclaude_laptop_bot`

**Important naming convention:**

- Username should be `teleclaude_{computer_name}_bot`
- This makes it clear which bot belongs to which computer

---

## Step 2: Create Shared Telegram Supergroup

All bots must join the **same supergroup** to communicate.

### Create Supergroup

1. In Telegram, create a new group
2. Add at least one other user (required to convert to supergroup)
3. Go to Group Settings → Convert to Supergroup
4. Enable Topics: Settings → Group Type → **Topics** (enable)
5. **Important**: Change group settings to allow bots:
   - Privacy → Who can add members → **Everyone**
   - Permissions → Add members → **Enabled**

### Add All Bots to Supergroup

1. Click "Add Member" in supergroup
2. Search for each bot username:
   - `@teleclaude_macbook_bot`
   - `@teleclaude_workstation_bot`
   - `@teleclaude_server_bot`
3. Add each bot to the group
4. Grant admin permissions to each bot:
   - Right-click bot → Promote to Admin
   - Enable: **Manage Topics**, **Send Messages**, **Edit Messages**, **Delete Messages**

### Get Supergroup ID

You need the supergroup ID for configuration. Use one of these methods:

**Method 1: Via @userinfobot**

1. Forward any message from the supergroup to [@userinfobot](https://t.me/userinfobot)
2. Bot will reply with group info including the ID
3. Note the ID (looks like `-1001234567890`)

**Method 2: Via Telegram API**

1. Temporarily enable logging in your first daemon
2. Start daemon and send a message in the supergroup
3. Check logs for `chat_id` value

---

## Step 3: Configure Each Computer

Each computer needs its own configuration with **unique bot token** and **computer name**.

### Configuration Files

On each computer, create/update these files:

**`.env` (unique per computer):**

```bash
# Macbook example:
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz_macbook_token
TELEGRAM_SUPERGROUP_ID=-1001234567890  # SAME for all computers
WORKING_DIR=/Users/username/teleclaude

# Workstation example:
TELEGRAM_BOT_TOKEN=987654321:ZYXwvuTSRqponMLKjihgFED_workstation_token
TELEGRAM_SUPERGROUP_ID=-1001234567890  # SAME for all computers
WORKING_DIR=/home/username/teleclaude
```

**`config.yml` (per computer):**

```yaml
computer:
  name: macbook # UNIQUE per computer (must match COMPUTER_NAME in .env)
  bot_username: teleclaude_macbook_bot # UNIQUE per computer
  default_shell: /bin/zsh
  default_working_dir: ${WORKING_DIR}
  trusted_dirs:
    - ${WORKING_DIR}
    - ~/projects

telegram:
  supergroup_id: ${TELEGRAM_SUPERGROUP_ID} # SAME for all computers
  is_master: true # Only ONE computer should be master (usually your primary workstation)

  # Whitelist of trusted bots (SAME for all computers)
  trusted_bots:
    - teleclaude_macbook_bot
    - teleclaude_workstation_bot
    - teleclaude_server_bot
    - teleclaude_laptop_bot

mcp:
  enabled: true
  transport: stdio
  claude_command: claude # Command to start Claude Code
```

**Critical points:**

- ✅ `computer.name` must be **unique** per computer
- ✅ `TELEGRAM_BOT_TOKEN` must be **unique** per computer
- ✅ `TELEGRAM_SUPERGROUP_ID` must be **same** for all computers
- ✅ `trusted_bots` list must include **all bots** on all computers (security whitelist)
- ✅ `telegram.is_master` should be `true` on **ONE computer only** (see Master Bot Pattern below)

---

### Master Bot Pattern

**Why only one master?**

When multiple bots are in the same Telegram supergroup, only **one bot** should register Telegram commands. This prevents duplicate command entries in Telegram's autocomplete UI.

**Configuration:**

```yaml
# Master computer (e.g., macbook) - registers commands
telegram:
  is_master: true

# Non-master computers (e.g., workstation, server) - clear their command lists
telegram:
  is_master: false  # Or omit this field (defaults to false)
```

**How it works:**

1. **Master bot** registers all commands with **trailing spaces**:

   - Example: `BotCommand("new_session ", "Create a new terminal session")`
   - The trailing space prevents Telegram from appending `@botname` in autocomplete
   - Commands become universal: `/new_session` works for any bot

2. **Non-master bots** clear their command lists:
   - Prevents duplicate command entries
   - All bots still respond to commands
   - Users don't see 3-4 copies of each command in autocomplete

**When to use is_master:**

- ✅ Set `is_master: true` on your **primary workstation** (the computer you interact with most)
- ✅ Set `is_master: false` (or omit) on all other computers
- ✅ Only change if you want a different computer to manage command registration

**Important:** All bots still handle commands regardless of `is_master` setting. This only affects command registration in Telegram's UI

---

## Step 4: Start Daemons

On each computer, start the TeleClaude daemon:

```bash
# On each computer:
cd ~/teleclaude  # Or wherever you installed TeleClaude
make start       # Start daemon to load new config
make status      # Verify daemon is running
```

**Verify daemon startup:**

```bash
tail -f logs/teleclaude.log
```

You should see:

```
INFO - Starting computer registry for macbook
INFO - Computer registry started: topic_id=12345, discovered 0 computers
INFO - Heartbeat sent for macbook
INFO - Registry polled: 1 total, 1 online
```

---

## Step 5: Verify Computer Discovery

After all daemons are running, check that they can see each other.

### Check "Online Now" Topic in Telegram

1. Open your Telegram supergroup
2. Look for topic named **"Online Now"** (created automatically)
3. You should see heartbeat messages from each computer:
   ```
   macbook - last seen at 2025-11-05 14:30:45
   workstation - last seen at 2025-11-05 14:30:48
   server - last seen at 2025-11-05 14:30:52
   ```

These messages update every 30 seconds (heartbeat mechanism).

### Test MCP Discovery

If you have Claude Code installed, you can test computer discovery:

```bash
# On computer 1 (macbook):
claude

# In Claude Code session:
> Use the teleclaude__list_computers MCP tool

# Expected output:
[
  {
    "name": "macbook",
    "bot_username": "@teleclaude_macbook_bot",
    "status": "online",
    "last_seen_ago": "5s ago"
  },
  {
    "name": "workstation",
    "bot_username": "@teleclaude_workstation_bot",
    "status": "online",
    "last_seen_ago": "8s ago"
  },
  {
    "name": "server",
    "bot_username": "@teleclaude_server_bot",
    "status": "online",
    "last_seen_ago": "12s ago"
  }
]
```

---

## Step 6: Configure Claude Code MCP Integration

To use TeleClaude's MCP tools from Claude Code, add the MCP server to your Claude Code config.

### Automatic Configuration (Recommended)

If you used `install.sh`, MCP is already configured. The installer merges TeleClaude's MCP server into your Claude Code config automatically.

### Manual Configuration

**Config file**: `~/.claude.json`

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

**Note:** This uses `socat` to bridge stdio to the daemon's Unix socket. Ensure `socat` is installed (`make init` installs it automatically).

### Verify MCP Tools Available

Start Claude Code and check available tools:

```bash
claude

# In Claude Code:
> What MCP tools are available?

# You should see:
- teleclaude__list_computers - List all online TeleClaude computers
- teleclaude__list_projects - List available project directories on a computer
- teleclaude__list_sessions - List active AI-to-AI sessions
- teleclaude__start_session - Start AI-to-AI session with remote computer
- teleclaude__send_message - Send message to a session
- teleclaude__get_session_data - Get session transcript data
- teleclaude__stop_notifications - Unsubscribe from session events without ending it
- teleclaude__end_session - Gracefully terminate a session
- teleclaude__deploy_to_all_computers - Deploy latest code to all computers
- teleclaude__send_file - Send a file to a session
```

---

## Testing AI-to-AI Communication

### Basic Test: List Computers

```bash
# On macbook, start Claude Code:
claude

# Ask Claude to list computers:
> Use teleclaude__list_computers to show me what computers are available
```

**Expected result**: List of all online computers with their status.

### Test Remote Command Execution

```bash
# On macbook, ask Claude to execute command on workstation:
> Use teleclaude MCP tools to ask the workstation computer to check its disk usage (df -h)
```

**What happens behind the scenes:**

1. Claude Code calls `teleclaude__start_session(target="workstation", title="Check disk usage")`
2. Macbook's MCP server creates Telegram topic: `$macbook > $workstation - Check disk usage`
3. Macbook sends `/claude_resume` to wake Claude Code on workstation
4. Workstation's daemon sees message, starts Claude Code in tmux
5. Macbook calls `teleclaude__send_message(session_id, "df -h")`
6. Workstation executes command, streams output back via Telegram
7. Macbook's MCP server yields chunks to Claude Code
8. Claude Code displays the disk usage from workstation

### Expected Telegram UI

In your supergroup, you'll see:

- Topic: `$macbook > $workstation - Check disk usage`
- Messages in topic:

  ````
  /claude_resume

  🤖 Starting Claude Code on workstation...

  ```
  Filesystem      Size  Used Avail Capacity
  /dev/sda1       500G  250G  250G    50%
  ````

  [Chunk 1/1]

  [Output Complete]

  ```

  ```

---

## Troubleshooting

### Computers Not Appearing in Discovery

**Problem**: `teleclaude__list_computers` returns empty list or missing computers.

**Solutions**:

1. **Check daemon is running** on each computer:

   ```bash
   make status
   ```

2. **Check "Online Now" topic** in Telegram:

   - Should see heartbeat messages from all computers
   - Messages should update every 30 seconds

3. **Check logs** for heartbeat errors:

   ```bash
   tail -100 logs/teleclaude.log | grep -i heartbeat
   ```

4. **Verify supergroup ID** is same in all `.env` files:

   ```bash
   grep SUPERGROUP .env
   ```

5. **Wait 60 seconds** - offline threshold is 60s, new computers take up to 60s to appear

### Permission Denied When Sending Commands

**Problem**: Error when trying to start session or send commands.

**Solutions**:

1. **Check trusted_bots whitelist** in `config.yml`:

   ```yaml
   telegram:
     trusted_bots:
       - teleclaude_macbook_bot
       - teleclaude_workstation_bot
       # Must include ALL bots
   ```

2. **Verify bot has admin permissions** in supergroup:

   - Open supergroup → Administrators
   - Check each bot has "Manage Topics" permission

3. **Check target computer is online**:
   ```bash
   # In Claude Code:
   > List computers - is workstation showing as online?
   ```

### Streaming Timeout

**Problem**: `teleclaude__send_message` times out waiting for response.

**Solutions**:

1. **Check target computer's daemon is running**:

   ```bash
   # On target computer:
   make status
   ```

2. **Check target computer logs** for errors:

   ```bash
   # On target computer:
   tail -100 logs/teleclaude.log
   ```

3. **Verify Claude Code is installed** on target computer:

   ```bash
   # On target computer:
   which claude
   ```

4. **Check tmux session exists** on target computer:
   ```bash
   # On target computer:
   tmux ls | grep "workstation"
   ```

### Messages Not Appearing in Telegram

**Problem**: Commands sent but no output appears in topic.

**Solutions**:

1. **Check topic exists** in supergroup (should be created automatically)

2. **Verify polling is active** - check target computer logs:

   ```bash
   tail -100 logs/teleclaude.log | grep -i polling
   ```

3. **Check for errors** in output formatting:
   ```bash
   tail -100 logs/teleclaude.log | grep -i "ERROR"
   ```

---

## Security Best Practices

### Bot Token Security

- ✅ **Never commit** `.env` files to git (already in `.gitignore`)
- ✅ **Restrict file permissions**: `chmod 600 .env`
- ✅ **Use separate tokens** for each computer (easier to revoke if compromised)
- ✅ **Rotate tokens periodically** via @BotFather

### Trusted Bots Whitelist

- ✅ **Only add known bots** to `trusted_bots` list
- ✅ **Keep whitelist synchronized** across all computers
- ✅ **Review whitelist** when adding/removing computers
- ✅ **Use clear naming convention** (e.g., `teleclaude_{computer}_bot`)

### Supergroup Access

- ✅ **Private supergroup** - Don't make it public
- ✅ **Invite-only** - Set "Who can add members" to Admins only
- ✅ **Review members** - Periodically check who has access
- ✅ **Remove old bots** - Delete bots from supergroup when decommissioning computers

---

## Advanced Configuration

### Custom Claude Command

If Claude Code is installed in a non-standard location or requires special setup:

```yaml
mcp:
  claude_command: /opt/claude/bin/claude --config /etc/claude/config.json
```

### Multiple Supergroups

You can run separate TeleClaude networks by using different supergroups:

**Production network:**

```bash
# .env
TELEGRAM_SUPERGROUP_ID=-1001111111111
```

**Testing network:**

```bash
# .env
TELEGRAM_SUPERGROUP_ID=-1002222222222
```

Bots in different supergroups won't see each other.

### Network Segmentation

Use `trusted_bots` to create isolated groups within same supergroup:

**Team A computers** (only trust each other):

```yaml
telegram:
  trusted_bots:
    - teleclaude_macbook_bot
    - teleclaude_workstation_bot
```

**Team B computers** (only trust each other):

```yaml
telegram:
  trusted_bots:
    - teleclaude_server_bot
    - teleclaude_laptop_bot
```

This prevents cross-team command execution while sharing the same Telegram supergroup.

---

## Monitoring and Maintenance

### Health Checks

**Check computer registry status:**

```bash
# View "Online Now" topic in Telegram supergroup
# Should see recent heartbeats from all computers (< 60s ago)
```

**Check daemon logs:**

```bash
# On each computer:
tail -100 logs/teleclaude.log | grep -E "(ERROR|WARNING)"
```

**Test MCP connectivity:**

```bash
# From Claude Code on any computer:
> List all available TeleClaude computers
```

### Log Rotation

Set up log rotation to prevent disk space issues:

**macOS** (`/etc/newsyslog.d/teleclaude.conf`):

```
# Rotate teleclaude logs daily, keep 7 days
logs/teleclaude.log 644 7 * @T00 GZ
```

**Linux** (`/etc/logrotate.d/teleclaude`):

```
logs/teleclaude.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
}
```

### Upgrading TeleClaude

When upgrading TeleClaude on multiple computers:

1. **Upgrade one computer at a time** (avoid simultaneous downtime)
2. **Test MCP tools** after each upgrade
3. **Check version compatibility** in release notes
4. **Monitor "Online Now"** - upgraded computer should reappear within 60s

---

## Example Use Cases

### Use Case 1: Log Analysis Across Servers

**Scenario**: Debug production issue by checking logs on multiple servers.

```bash
# On macbook, in Claude Code:
> I'm seeing errors in the app. Can you check logs on:
> 1. webserver computer - /var/log/nginx/error.log
> 2. appserver computer - /var/log/app/error.log
> Use teleclaude MCP tools to check both servers concurrently
```

Claude Code will:

1. Start sessions with both computers
2. Execute log commands in parallel
3. Aggregate results for analysis
4. Identify common error patterns

### Use Case 2: Distributed Testing

**Scenario**: Run tests on multiple platforms simultaneously.

```bash
# On macbook, in Claude Code:
> Run the test suite on:
> 1. macbook (macOS)
> 2. ubuntu_vm (Linux)
> 3. windows_vm (Windows)
> Use teleclaude to run tests in parallel and compare results
```

### Use Case 3: Deploy and Verify

**Scenario**: Deploy code to server and verify it's working.

```bash
# On macbook, in Claude Code:
> 1. Deploy latest code to production_server using git pull
> 2. Restart the application service
> 3. Check service status and recent logs
> 4. Verify HTTP endpoint responds correctly
> Use teleclaude to execute all steps on production_server
```

---

## Getting Help

If you encounter issues not covered in this guide:

1. **Check documentation**:

   - `README.md` - Installation and basic usage
   - `docs/architecture.md` - Technical architecture details
   - `docs/troubleshooting.md` - Common issues and fixes

2. **Check logs**:

   ```bash
   tail -200 logs/teleclaude.log
   ```

3. **Verify configuration**:

   ```bash
   cat config.yml | grep -A5 "computer:"
   cat config.yml | grep -A5 "mcp:"
   cat .env
   ```

4. **Test with simple command first**:

   ```bash
   # In Claude Code:
   > Use teleclaude to run "echo test" on workstation
   ```

5. **File an issue**: [GitHub Issues](https://github.com/your-org/teleclaude/issues)

---

## Summary Checklist

Before declaring multi-computer setup complete, verify:

- [ ] Each computer has unique bot token and computer name
- [ ] All bots added to same Telegram supergroup
- [ ] All bots have admin permissions (Manage Topics)
- [ ] "Online Now" topic shows heartbeats from all computers
- [ ] `trusted_bots` whitelist includes all bots (on all computers)
- [ ] `teleclaude__list_computers` returns all computers
- [ ] Successfully sent test command from one computer to another
- [ ] Received streaming output in Claude Code
- [ ] Telegram topics show AI-to-AI communication flow

Once all items checked, your multi-computer TeleClaude network is ready! 🎉
