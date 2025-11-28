# Exit Code Detection Refactoring - Requirements

## Problem Statement

The current exit marker system has unnecessary complexity:

1. **Dual decision points**: System checks both "what's running" AND "what am I starting"
2. **Over-exclusion**: Commands like `vim`, `claude`, `python script.py` don't get exit markers when started
3. **False idle warnings**: Interactive commands trigger 60-second idle timeout instead of immediate completion detection
4. **Lpoll infrastructure sprawl**: ~100 lines of lpoll list code, config, and special-case handling

### Current (Buggy) Behavior

```python
# User starts vim
current_is_interactive = is_long_running_command("bash")  # False
sending_interactive_command = is_long_running_command("vim")  # True
append_exit_marker = False  # WRONG - blocks marker!

# Sent to tmux: vim file.txt (NO MARKER)
# User quits vim → no marker → polls 60s until idle timeout
```

### Root Cause

The system was built on a misunderstanding of shell command chaining. Someone thought:

> "If I run `vim; echo 'DONE'`, vim runs forever so echo never fires"

**But this is wrong!** Sequential shell commands (`;`, `&&`, `||`) WAIT for each command to complete:

```bash
vim file.txt; echo "__EXIT__abc123__$?__"

# Execution:
1. Shell runs vim (blocks, waits)
2. User quits vim
3. Shell continues, runs echo
4. Marker detected ✓
```

## Goals

### Primary Goal: Simplify Exit Marker Logic

Replace dual decision points with single shell-readiness check:

**From (current):**
```python
current_is_interactive = is_long_running_command(current_command)
sending_interactive_command = is_long_running_command(command)

if current_is_interactive or sending_interactive_command:
    append_exit_marker = False
```

**To (proposed):**
```python
current_command = get_current_command(tmux_session)
is_shell_ready = current_command in SHELL_NAMES

if is_shell_ready:
    append_exit_marker = True
else:
    append_exit_marker = False  # Something is running, sending input
```

### Secondary Goals

1. **Eliminate lpoll infrastructure**: Remove `LPOLL_DEFAULT_LIST`, `is_long_running_command()`, `lpoll_extensions` config
2. **Faster completion detection**: Interactive commands exit immediately instead of 60s timeout
3. **Enable command chaining**: Allow `vim file.txt && make test` (currently blocked)
4. **Reduce code complexity**: -85 lines of lpoll-related code
5. **Simpler mental model**: No hidden "long poll list" concept for users or developers

## Requirements

### R1: Shell Detection Using User's Configured Shell

**Requirement**: Compute user's shell once at module import time, use for inline comparison

**Acceptance Criteria**:
- Shell determined ONCE at module import time: `_SHELL_NAME` module constant
- Reads from `SHELL` environment variable (normal context)
- Falls back to `pwd.getpwuid(os.getuid()).pw_shell` (daemon context)
- Extracts basename from shell path (e.g., "zsh" from "/bin/zsh")
- Comparison: `not current_command or current_command.lower() == _SHELL_NAME`
- No function wrapper - direct inline comparison
- No hardcoded shell list - uses actual user's shell
- Performance: O(1) comparison, no repeated lookups

**Example**:
```python
# Module level (computed once at import):
_SHELL_NAME = Path(os.environ.get("SHELL") or pwd.getpwuid(os.getuid()).pw_shell).name.lower()
# → "zsh"

# In send_keys() (inline comparison):
current_command = await get_current_command(session_name)
append_exit_marker = not current_command or current_command.lower() == _SHELL_NAME

# Cases:
# current_command = "zsh" → True (matches shell)
# current_command = "vim" → False (not shell)
# current_command = None → True (safe default)
```

### R2: Automatic Exit Marker Decision

**Requirement**: Move exit marker decision into `send_keys()`, remove `append_exit_marker` parameter

**Acceptance Criteria**:
- `send_keys()` automatically decides based on shell readiness
- No explicit `append_exit_marker=True/False` in calling code
- File handler, restart script, daemon all simplified
- Marker appended when shell ready, skipped when process running

**Before**:
```python
# Caller explicitly specifies
await send_keys(session, "vim file.txt", append_exit_marker=False)
```

**After**:
```python
# Automatic decision
await send_keys(session, "vim file.txt")
# Internally checks: is_shell_ready() → True → appends marker
```

### R3: Remove Lpoll Infrastructure & default_shell Config

**Requirement**: Delete all lpoll-related code, configuration, and default_shell config

**Acceptance Criteria**:
- Delete `LPOLL_DEFAULT_LIST` constant (42 items)
- Delete `is_long_running_command()` function
- Delete `has_command_separator()` function and validation
- Remove `lpoll_extensions` from config.py and config.yml.sample
- Remove `default_shell` from config.py and config.yml.sample
- Remove all `sending_interactive_command` checks from daemon.py
- Remove all `shell=config.computer.default_shell` parameters
- Remove command chaining validation (allow chaining now)
- Update `create_tmux_session()` to use tmux's automatic $SHELL detection

**Code Deletions**:
- `terminal_bridge.py`: Lines 20-108 (~88 lines)
- `config.py`: `lpoll_extensions` field + `default_shell` field
- `config.yml.sample`: `lpoll_extensions` line + `default_shell` line
- `daemon.py`: `sending_interactive_command` checks (2 locations) + `shell=` parameters (3 locations)
- `command_handlers.py`: `shell=` parameters (2 locations)
- `restart_claude.py`: `shell=` parameter (1 location)

### R4: Preserve Current Behavior for Valid Cases

**Requirement**: Ensure edge cases work correctly

**Acceptance Criteria**:

**Case 1: Input to running process**
```python
# User uploads file while vim is running
current_command = "vim"
is_shell_ready("vim")  # False
# Result: No marker (correct - sending input to vim)
```

**Case 2: Starting interactive command**
```python
# User starts vim from shell
current_command = "bash"
is_shell_ready("bash")  # True
# Result: Marker appended (NEW - immediate detection on exit)
```

**Case 3: Long-running script**
```python
# User runs ./build.sh
current_command = "bash"
is_shell_ready("bash")  # True
# Result: Marker appended (unchanged - works correctly)
```

**Case 4: Nested shells**
```python
# User runs bash to start nested shell
current_command = "bash"
is_shell_ready("bash")  # True
# Result: Marker appended
# Execution: bash; echo "__EXIT__..."
# Shell waits for nested bash to exit, then runs echo (correct!)
```

### R5: Comprehensive Testing

**Requirement**: Update test suite to cover new behavior

**Acceptance Criteria**:

**Unit Tests**:
- `test_is_shell_ready()` - shell detection logic
- Remove `test_is_long_running_command()` tests
- Remove `test_has_command_separator()` tests
- Update `test_append_exit_marker_*()` tests

**Integration Tests**:
- `test_vim_exits_with_marker()` - verify immediate detection
- `test_input_to_running_vim_no_marker()` - verify input handling
- `test_nested_shell_marker()` - verify nested shells work
- `test_command_chaining_allowed()` - verify chaining works now

**Edge Case Tests**:
- Unknown shell names (default to ready)
- `get_current_command()` returns None (safe default)
- Background jobs (`python script.py &`)

### R6: Documentation Updates

**Requirement**: Update documentation to reflect new behavior

**Acceptance Criteria**:
- Update `CLAUDE.md` - remove lpoll list references
- Update `config.yml.sample` - remove lpoll_extensions
- Create `docs/exit-markers.md` - explain shell detection
- Archive `analysis_exit_marker_simplification.md` and `refactoring_impact_analysis.md`

## Non-Requirements

### What This Does NOT Change

1. **Marker format**: Still `__EXIT__{marker_id}__$?__` (hash-based IDs)
2. **Polling logic**: Still uses `output_poller.py` to detect markers
3. **Idle timeout**: Still 60s fallback (but rarely triggered now)
4. **Key input handling**: Still separate path for Tab/Esc/Arrow keys
5. **File upload**: Still works (automatic detection handles it)

### What We're NOT Fixing

1. **Background job behavior**: `python script.py &` marker fires on spawn (not job completion)
   - This is technically correct (exit code = spawn success)
   - Document behavior, don't change it

2. **Uncommon shells**: fish/nu/elvish might not be in shell list
   - Can be added later if users request
   - System defaults to "ready" if unknown (safe)

3. **Shell syntax edge cases**: Unclosed quotes, incomplete syntax
   - Pre-existing issue with marker appending
   - Not introduced by this refactoring

## Success Metrics

### Quantitative
- [ ] Test coverage ≥90% for new shell detection code
- [ ] All existing tests pass (after updates)
- [ ] Code reduction: -85 lines removed
- [ ] Interactive command completion: <2s (currently 60s)

### Qualitative
- [ ] Code is simpler to understand (one decision point vs two)
- [ ] No user-reported bugs after 1 week in production
- [ ] Command chaining works as expected
- [ ] No false "hung up" warnings after interactive commands

## Rollout Strategy

### Phase 1: Development
1. Implement changes in isolation
2. Run comprehensive test suite
3. Manual testing on dev machine

### Phase 2: Single Computer Validation
1. Deploy to one non-critical computer (RasPi)
2. Monitor logs for 24 hours
3. Test all common use cases

### Phase 3: Full Deployment
1. Deploy to all computers via `/deploy`
2. Monitor Telegram for issues
3. Verify no regression

### Rollback Plan
```bash
git revert <commit-hash>
make restart
# Daemon restarts with old code in ~2s
```

## Dependencies

**None** - This is a self-contained refactoring with no external dependencies.

## Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Uncommon shell not detected | LOW | LOW | Add to shell list on request |
| get_current_command() fails | LOW | MEDIUM | Default to ready (safe) |
| Background job confusion | LOW | LOW | Document behavior |
| Performance regression | VERY LOW | LOW | Test before deploy |

**Overall Risk**: LOW - Well-testable, clear failure modes, simple rollback

## Questions for Clarification

**None** - Requirements are clear and aligned with user's analysis.
