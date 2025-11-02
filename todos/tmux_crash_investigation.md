# Tmux Server Crash Investigation

## Incident Summary

**Date:** 2025-11-01 ~17:03:30
**Error:** `no server running on /private/tmp/tmux-502/default`
**Impact:** Tmux session `mozbook-session-833a2a5a` crashed after running for ~10 minutes with no output

## Timeline

1. **16:52:57** - User triggered `/claude` command
2. **16:52:57-17:03:30** - Polling loop ran for ~10m 36s (603 iterations)
3. **17:03:30** - Tmux server crashed: "no server running on /private/tmp/tmux-502/default"
4. **17:03:30** - Daemon detected session death and stopped polling

## Evidence from Logs

```
2025-11-01 17:03:30.747 INFO > teleclaude/core/terminal_bridge.py: Session mozbook-session-833a2a5a does not exist: returncode=1, stderr=no server running on /private/tmp/tmux-502/default
2025-11-01 17:03:30.747 INFO > teleclaude/daemon.py: Process exited for b0e39562, stopping poll
```

## Initial Context

During the incident:
- Command started but produced **zero output** for entire 10-minute period
- Daemon was polling tmux session every 1 second via `capture_pane`
- Session existed for 603 checks, then suddenly died
- Shell initialization had errors: `operation not permitted: /Users/Morriz/.dotfiles/runcom/.common`

## Potential Root Causes

### 1. Permissions Issues

**Hypothesis:** `/private/tmp/tmux-502/` directory has incorrect ownership/permissions

**Investigation needed:**
- Check ownership: `ls -la /private/tmp/ | grep tmux`
- Check socket permissions: `ls -la /private/tmp/tmux-502/` (if exists)
- Verify user can create sockets: `touch /private/tmp/test && rm /private/tmp/test`

### 2. Stale Socket Files

**Hypothesis:** Old tmux sockets not cleaned up properly, causing conflicts

**Investigation needed:**
- List all tmux sockets: `tmux -L default list-sessions` vs `tmux list-sessions`
- Check for zombie processes: `ps aux | grep tmux`
- Inspect socket directory: `find /private/tmp -name "tmux-*" -type d`

### 3. Resource Exhaustion

**Hypothesis:** System ran out of PTYs or file descriptors

**Investigation needed:**
- Check open file limits: `ulimit -n`
- Check current open files: `lsof -p <daemon_pid> | wc -l`
- Check PTY allocation: `ls -l /dev/ttys*`
- Monitor during operation: `watch -n1 'lsof -c tmux | wc -l'`

### 4. Tmux Server Timeout/Crash

**Hypothesis:** Tmux server killed itself due to timeout or resource constraints

**Investigation needed:**
- Check tmux server logs (if any): `tmux show-messages`
- Review system logs for tmux: `/usr/bin/log show --predicate 'processImagePath CONTAINS "tmux"' --last 1h`
- Test tmux stability: Run long-lived session with frequent `capture-pane` calls

### 5. macOS-Specific Issues

**Hypothesis:** macOS sandbox or security features interfering with socket creation

**Investigation needed:**
- Check console logs: `log show --predicate 'eventMessage CONTAINS "tmux"' --last 1h --info`
- Verify no app sandboxing: `codesign -d --entitlements - $(which tmux)`
- Test in different socket location: `tmux -S /tmp/test-socket new`

## Diagnostic Commands

Run these to gather information:

```bash
# Current tmux state
tmux list-sessions 2>&1
ps aux | grep tmux

# Socket inspection
ls -la /private/tmp/ | grep tmux
find /private/tmp -name "tmux-*" -type d -exec ls -la {} \;

# Resource limits
ulimit -a
lsof -c tmux | wc -l

# System logs (macOS)
/usr/bin/log show --predicate 'eventMessage CONTAINS "tmux" OR processImagePath CONTAINS "tmux"' --last 2h --info

# Clean slate test
tmux kill-server
tmux new -s crash-test
# Leave running, monitor logs
```

## Reproduction Attempt

To reproduce the crash:

1. Start a tmux session: `tmux new -s test-crash`
2. Send a command that produces no output: `cat` (waits for input)
3. Poll aggressively: `watch -n1 'tmux capture-pane -t test-crash -p'`
4. Monitor for crash after ~10 minutes

## Workarounds (If Crash Confirmed)

If this is a recurring issue:

1. **Reduce polling frequency** - Change from 1s to 2s intervals
2. **Limit capture size** - Use `-S -100` instead of `-S -` to limit scrollback
3. **Alternative socket location** - Use `tmux -S ~/.tmux-socket` instead of default
4. **Tmux server restart** - Periodically restart tmux server (nuclear option)

## Next Steps

- [ ] Run diagnostic commands above
- [ ] Attempt reproduction with aggressive polling
- [ ] Check system logs for related errors
- [ ] Test with alternative socket locations
- [ ] Consider rate-limiting tmux operations if confirmed

## Notes

- This may be related to the shell initialization error: `operation not permitted: /Users/Morriz/.dotfiles/runcom/.common`
- Could indicate deeper permission/security issues beyond just tmux
- No similar crashes reported in logs before or after this incident (needs verification)

## References

- [Tmux man page - socket handling](https://man.openbsd.org/tmux#COMMANDS)
- [macOS PTY limits](https://developer.apple.com/library/archive/technotes/tn2083/_index.html)
- Related code: `teleclaude/core/terminal_bridge.py:159` (capture_pane)
