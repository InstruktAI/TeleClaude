# Exit Marker Detection

## Overview

TeleClaude uses **exit markers** to detect when commands complete in tmux sessions. This allows the daemon to know when to stop polling for output and update the user interface.

## How Exit Markers Work

### Shell-Readiness Detection

The system automatically decides whether to append exit markers based on **shell readiness**:

```python
# Automatic decision in send_keys():
current_command = await get_current_command(session_name)
append_exit_marker = not current_command or current_command.lower() == _SHELL_NAME
```

**When markers ARE appended:**
- Shell is ready (no command running, or shell itself is running)
- Current command is `None` (new session)
- Current command matches `$SHELL` (bash, zsh, sh, fish, dash)

**When markers are NOT appended:**
- A process is running (vim, claude, top, etc.)
- Input is being sent to the running process

### Exit Marker Format

```bash
command; echo "__EXIT__{marker_id}__$?__"
```

- `marker_id`: Auto-generated MD5 hash (8 chars)
- `$?`: Exit code of the command
- Marker fires immediately when command completes

### Shell Detection

Shell detection happens once at module import time:

```python
import pwd
from pathlib import Path

# User's shell basename, computed once at import
_SHELL_NAME = Path(os.environ.get("SHELL") or pwd.getpwuid(os.getuid()).pw_shell).name.lower()
```

Supported shells: bash, zsh, sh, fish, dash

## Benefits

### Before (Complex lpoll System)

- **Dual decision points**: Check "what's running" AND "what am I starting"
- **Over-exclusion**: Commands like `vim` didn't get markers when started
- **False idle warnings**: 60-second timeout instead of immediate completion
- **~100 lines of lpoll infrastructure**

### After (Simple Shell-Readiness)

- **Single decision point**: Check if shell is ready
- **Immediate completion**: Vim exits detected in <2s (was 60s)
- **Command chaining works**: `vim && ls` no longer rejected
- **Simpler codebase**: -100 lines of code

## Examples

### Normal Command (Shell Ready)

```bash
# Shell is ready → marker appended
$ echo "hello"
# Executes: echo "hello"; echo "__EXIT__abc12345__$?__"
# Marker fires immediately with exit code 0
```

### Interactive Process (Vim Running)

```bash
# Start vim
$ vim file.txt
# Vim is running → no marker on subsequent input

# User sends input to vim (via file upload or voice)
:wq
# No marker appended, input goes directly to vim
```

### Nested Shell

```bash
# Start bash
$ bash
# Bash is the shell → marker appended
# Executes: bash; echo "__EXIT__def67890__$?__"

# Inside nested bash
$ exit
# Marker fires, showing bash exited
```

## Troubleshooting

### Command Doesn't Complete

**Check what's running:**
```python
current_command = await get_current_command(session_name)
print(f"Current command: {current_command}")
```

If `current_command` is not the shell, no marker was appended.

### Uncommon Shells

If using an uncommon shell (nu, elvish, etc.):

1. Check `_SHELL_NAME` value at runtime
2. If unknown, add to shell detection logic
3. Currently defaults to "ready" if unknown (safe)

### Background Jobs

```bash
python script.py &
# Marker fires on spawn (exit code 0), not job completion
# This is correct behavior (spawn success)
```

## Implementation Details

### API Changes

**Old API (manual control):**
```python
await send_keys(session, "ls", append_exit_marker=True, shell="/bin/bash")
```

**New API (automatic):**
```python
success, marker_id = await send_keys(session, "ls")
```

### Return Value

```python
tuple[bool, Optional[str]]
# (True, "abc12345")  - Success, marker appended
# (True, None)         - Success, no marker (process running)
# (False, None)        - Failed to send keys
```

### Testing

Tests verify automatic marker decision:

```python
# Test shell ready → marker appended
with patch.object(terminal_bridge, "get_current_command", return_value="zsh"):
    success, marker_id = await send_keys("test-session", "ls")
    assert marker_id is not None

# Test process running → no marker
with patch.object(terminal_bridge, "get_current_command", return_value="vim"):
    success, marker_id = await send_keys("test-session", "input")
    assert marker_id is None
```

## Known Edge Cases

### Syntax Errors

Unclosed quotes or incomplete syntax can break marker appending:

```bash
echo "hello
# Marker may not work correctly
```

Future improvement: Use `\n` separator instead of `;`

### False Positives

Commands that print similar patterns won't confuse the system:

```bash
echo "__EXIT__fake123__0__"
# Polling checks marker_id matches, so false positives are ignored
```

## History

This simplified approach replaced the complex `lpoll` (long-poll) system that maintained a list of 42+ "long-running" commands and complex validation logic. The key insight was that shell command chaining (`;`, `&&`, `||`) waits for completion, so we don't need to prevent markers on specific commands.
