# Fix Polling Exit Detection with Hash-Based Markers

## Problem Summary

The current exit detection uses marker COUNTING which fails for fast commands:
- Scrollback contains old markers from previous commands
- Baseline is established AFTER command completes (includes new marker)
- Count never increases → polling runs forever
- "Every other" works because next command's marker triggers exit

## Solution: Hash-Based Unique Markers

Replace counting with exact marker matching using unique hash IDs.

### New Marker Format

```
# OLD: __EXIT__$?__
# NEW: __EXIT__<marker_id>__$?__

# Example: __EXIT__a1b2c3d4__0__
```

### How It Works

1. **Generate unique marker ID** when command is sent:
   ```python
   marker_id = hashlib.md5(f"{command}:{time.time()}".encode()).hexdigest()[:8]
   ```

2. **Send command with unique marker**:
   ```python
   f'{command}; echo "__EXIT__{marker_id}__$?__"'
   ```

3. **Poll for exact marker** (no counting, no baseline):
   ```python
   match = re.search(f"__EXIT__{marker_id}__(\\d+)__", output)
   if match:
       exit_code = int(match.group(1))
       # DONE - command finished
   ```

### Why This Is Reliable

- **No baseline logic** - just search for a specific string
- **Immune to old scrollback** - old markers have different hashes
- **Fast commands detected immediately** - marker is unique, found on first poll
- **No heuristics** - no "chars_after < 50" magic numbers

## Implementation Checklist

- [ ] Add `marker_id` parameter to `terminal_bridge.send_keys()`
- [ ] Generate marker_id in `daemon._execute_terminal_command()`
- [ ] Pass marker_id through `polling_coordinator.poll_and_send_output()`
- [ ] Simplify `output_poller.poll()` - search for exact marker
- [ ] Update `_extract_exit_code()` to use marker_id pattern
- [ ] Run `make test` and fix any broken tests
- [ ] Run `make restart` to deploy

## Files to Modify

| File | Change |
|------|--------|
| `teleclaude/core/terminal_bridge.py` | `send_keys()`: Accept `marker_id` param, include in exit marker |
| `teleclaude/daemon.py` | `_execute_terminal_command()`: Generate marker_id, pass to send_keys and polling |
| `teleclaude/core/polling_coordinator.py` | `poll_and_send_output()`: Accept marker_id, pass to poller |
| `teleclaude/core/output_poller.py` | `poll()`: Accept marker_id, search for exact marker instead of counting |
| `tests/unit/test_output_poller.py` | Update tests for new marker format |
