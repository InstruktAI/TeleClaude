# Troubleshooting Guide

## Daemon Won't Start or Crashes Immediately

If the daemon won't start or is crashing immediately, follow these steps:

1. **Unload the service** (disable auto-restart temporarily):

   ```bash
   # macOS
   launchctl unload ~/Library/LaunchAgents/ai.instrukt.teleclaude.daemon.plist

   # Linux
   sudo systemctl stop teleclaude
   ```

2. **Kill any remaining processes**:

   ```bash
   pkill -9 -f teleclaude.daemon
   rm -f teleclaude.pid
   ```

3. **Test daemon startup** (auto-terminates after 5 seconds):

   ```bash
   timeout 5 .venv/bin/python -m teleclaude.daemon 2>&1 | tee /tmp/daemon_test.txt
   ```

   Check the output - if you see "Uvicorn running" and no errors, it works.

4. **If there are errors**, check the captured output:

   ```bash
   cat /tmp/daemon_test.txt
   ```

5. **Once startup works, reload the service**:

   ```bash
   # macOS
   launchctl load ~/Library/LaunchAgents/ai.instrukt.teleclaude.daemon.plist

   # Linux
   sudo systemctl start teleclaude
   ```

6. **Verify it's running**:
   ```bash
   make status
   ```

**NEVER run the daemon in foreground with `make dev` in production - the service must always be up.**

## Common Errors

- **"Another daemon instance is already running"**: Kill all processes with `pkill -9 -f teleclaude.daemon` and remove `teleclaude.pid`
- **"This Updater is not running!"**: Telegram adapter failed to start - check bot token in `.env`
- **"Command 'X' is not a valid bot command"**: Telegram commands cannot contain hyphens, use underscores instead
- **Syntax errors**: Run `make lint` to check for Python syntax issues
- **Import errors**: Run `make install` to ensure all dependencies are installed
- **EBADF errors in tmux sessions**: This was caused by pipe file descriptors leaking from the daemon's tmux command calls. Every time the daemon called a tmux command with `stdout=PIPE, stderr=PIPE`, these pipes could leak into the tmux session environment, causing Node.js child_process.spawn() to fail with EBADF. Fixed by removing pipe capture from all tmux commands that don't need output (send-keys, send-signal, kill-session, etc.). Only commands that need output (capture-pane, list-sessions, etc.) use PIPE. tmux creates proper PTYs automatically for sessions

## Redis Adapter Issues

### Connection Refused

**Error:** `Failed to connect to Redis: Error 61 connecting to <host>:<port>`

**Possible causes:**
1. Redis server is not running
2. Wrong host or port in config
3. Firewall blocking connection
4. Redis bound to localhost only (not 0.0.0.0)

**Solutions:**

```bash
# On the Redis server:

# 1. Check if Redis is running
sudo systemctl status redis-server
ps aux | grep redis-server

# 2. Check which port Redis is listening on
sudo netstat -tlnp | grep redis
# Should show: 0.0.0.0:<port> (not 127.0.0.1:<port>)

# 3. Check Redis bind configuration
sudo grep "^bind" /etc/redis/redis.conf
# Should be: bind 0.0.0.0 (for external access)

# 4. Check firewall
sudo ufw allow <port>/tcp

# 5. Restart Redis after config changes
sudo systemctl restart redis-server
```

**On TeleClaude side:**

```bash
# Verify Redis config in config.yml
grep -A 10 "^redis:" config.yml

# Test connection manually
redis-cli -h <host> -p <port> -a <password> ping
```

### Invalid Password Error

**Error:** `invalid username-password pair or user is disabled`

**Solutions:**

1. **Check password in `.env` file:**
   ```bash
   grep REDIS_PASSWORD .env
   ```

2. **Test password locally on Redis server:**
   ```bash
   redis-cli -h 127.0.0.1 -p <port> -a '<password>' ping
   ```

3. **Verify Redis AUTH is configured:**
   ```bash
   sudo grep "^requirepass" /etc/redis/redis.conf
   ```

4. **For Redis 6+ with ACL users:**
   ```bash
   # Check if user is disabled
   redis-cli -p <port> ACL LIST
   ```

### SSL/TLS Connection Issues

**Error:** `Protocol Error: b'HTTP/1.1 400 Bad Request'`

**Solution:** Use `rediss://` (with double 's') for SSL/TLS connections:

```yaml
# config.yml
redis:
  url: rediss://redis.example.com:6379  # Note: rediss:// not redis://
```

### Adapter Not Loading

**Symptom:** Logs show "Loaded Telegram adapter" but no "Loaded Redis adapter"

**Check:**

```bash
# 1. Verify redis is enabled in config.yml
grep -A 2 "^redis:" config.yml | grep enabled

# 2. Check for startup errors in logs
tail -100 /var/log/instrukt-ai/teleclaude/teleclaude.log | grep -i redis

# 3. Verify redis package is installed
.venv/bin/pip list | grep redis
```

**Solution:**

```bash
# Install redis if missing
.venv/bin/pip install redis

# Set enabled: true in config.yml
# Restart daemon
make restart
```

## Service Management Commands

### Linux (systemd)

```bash
# Check status
sudo systemctl status teleclaude

# Stop service
sudo systemctl stop teleclaude

# Start service
sudo systemctl start teleclaude

# Restart service
sudo systemctl restart teleclaude

# View logs
sudo journalctl -u teleclaude -f

# Disable service (prevent auto-start on boot)
sudo systemctl disable teleclaude
```

### macOS (launchd)

```bash
# Check status
launchctl list | grep teleclaude

# Stop service
launchctl unload ~/Library/LaunchAgents/ai.instrukt.teleclaude.daemon.plist

# Start service
launchctl load ~/Library/LaunchAgents/ai.instrukt.teleclaude.daemon.plist

# View logs
tail -f /var/log/instrukt-ai/teleclaude/teleclaude.log
```

**Note:** It is acceptable to kill the daemon process directly (e.g., `kill <PID>`). The service will automatically restart it within 10 seconds.

## Debugging Logs

### Basic Log Monitoring

```bash
# Monitor daemon logs in real-time
tail -f /var/log/instrukt-ai/teleclaude/teleclaude.log
```

### CRITICAL: When Debugging Log Issues

1. **ALWAYS check timestamps first** - Don't assume logs are current
2. **Check if logs were rotated/cleared** - Look for gaps in timestamps or check file modification time with `ls -lh /var/log/instrukt-ai/teleclaude/teleclaude.log`
3. **Use precise time ranges** - When searching logs, use timestamps from the logs themselves, not assumptions
4. **Example workflow:**

   ```bash
   # Check log file age and size
   ls -lh /var/log/instrukt-ai/teleclaude/teleclaude.log

   # Check first and last timestamps
   head -5 /var/log/instrukt-ai/teleclaude/teleclaude.log  # First entries
   tail -5 /var/log/instrukt-ai/teleclaude/teleclaude.log  # Most recent entries

   # Search for specific time range
   grep "2025-10-31 16:4[0-9]:" /var/log/instrukt-ai/teleclaude/teleclaude.log | grep -E "(Command|Message|ERROR)"
   ```

5. **Before testing** - Note the current time and look for log entries AFTER that time
6. **When user reports an issue** - Ask for the approximate time and search around that timestamp

### Checking macOS System Logs

Use the `/usr/bin/log show` command to check system logs for launchd/daemon errors:

```bash
# Check last 5 minutes for teleclaude mentions (simple grep)
/usr/bin/log show --last 5m --info 2>&1 | grep -i teleclaude

# Check last hour
/usr/bin/log show --last 1h --info 2>&1 | grep -i teleclaude

# Check specific predicate (more targeted, no grep needed)
/usr/bin/log show --predicate 'eventMessage CONTAINS "teleclaude"' --last 10m --info
```

**IMPORTANT**:

- Use `/usr/bin/log` (full path) to avoid conflicts with shell built-ins in Bash
- The `--last` flag takes time units directly (e.g., `5m`, `1h`, `30s`) **without quotes**

## Known Limitations

### Topic Deletion Leaves Orphaned Sessions

**Issue:** When you delete a Telegram forum topic (not just close it), the session remains in the database as active.

**Why:** Telegram does not send deletion events to bots. The Bot API only provides events for:
- Topic created (`forum_topic_created`)
- Topic closed (`forum_topic_closed`) - ✅ Handled
- Topic reopened (`forum_topic_reopened`) - ✅ Handled
- Topic edited (`forum_topic_edited`)

**Workaround:** Use topic close instead of delete for clean session lifecycle:
1. Close the topic (we handle cleanup automatically)
2. Later, delete the topic if needed

**Impact:** Orphaned sessions consume minimal resources (database entries only). The tmux session and polling will continue until manually cleaned up with `/exit` or by killing the tmux session directly.
