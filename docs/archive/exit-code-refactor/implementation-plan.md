# Exit Code Detection Refactoring - Implementation Plan

## Overview

**Goal**: Replace lpoll infrastructure with simple shell-readiness detection
**Estimated Tasks**: 21 tasks across 7 groups
**Risk Level**: LOW - Well-testable, clear rollback path

## Task Groups

### Group 1: Remove default_shell Config & Use $SHELL

**Dependencies**: None
**Files**: `teleclaude/config.py`, `config.yml.sample`, `teleclaude/core/terminal_bridge.py`

- [x] **PARALLEL** Remove `default_shell` from config
  - Remove `default_shell: str` from `ComputerConfig` dataclass (config.py line 59)
  - Remove `"default_shell": "bash"` from DEFAULT_CONFIG (config.py line 142)
  - Remove `default_shell` parsing in `_load_config()` (config.py line 249)
  - Remove `default_shell: /bin/zsh` line from `config.yml.sample` (line 7)

- [x] **PARALLEL** Update `create_tmux_session()` to use $SHELL
  - Remove `shell: str` parameter (let tmux use $SHELL automatically)
  - Remove `shell_cmd = f"{shell} -l"` line (line 130)
  - Remove `cmd.append(shell_cmd)` line (line 150)
  - tmux will automatically use $SHELL from environment
  - Update docstring to reflect automatic shell detection

- [x] **PARALLEL** Add module-level shell detection
  - Add at module level (top of file, after imports):
    - `import pwd` (for passwd fallback)
    - `_SHELL_NAME = Path(os.environ.get("SHELL") or pwd.getpwuid(os.getuid()).pw_shell).name.lower()`
    - Add comment: `# User's shell basename, computed once at import`

- [x] **PARALLEL** Update `send_keys()` to auto-decide exit markers
  - Call `get_current_command(session_name)` at start of function
  - Compute: `append_exit_marker = not current_command or current_command.lower() == _SHELL_NAME`
  - Remove `append_exit_marker` parameter (internal decision now)
  - Remove `shell` parameter (no longer needed)
  - Update docstring to explain automatic shell detection
  - Keep `marker_id` parameter for testing flexibility

### Group 2: Daemon Simplification

**Dependencies**: Group 1 (requires `_SHELL_NAME` constant to exist)
**Files**: `teleclaude/daemon.py`

- [x] **SEQUENTIAL** Simplify `_execute_terminal_command()` (lines 602-649)
  - Remove `current_command = await terminal_bridge.get_current_command(...)` (line 603)
  - Remove `current_is_interactive = ...` (line 604)
  - Remove `sending_interactive_command = ...` (line 605)
  - Remove entire logging block (lines 607-616)
  - Remove override logic (lines 618-632)
  - Remove `append_exit_marker` parameter from function signature
  - Remove `shell=config.computer.default_shell` from `send_keys()` call (line 643)
  - Remove `append_exit_marker=append_exit_marker` from `send_keys()` call (line 647)
  - Keep `marker_id` generation for polling

- [x] **SEQUENTIAL** Simplify `handle_message()` (lines 870-909)
  - Remove `current_command = await terminal_bridge.get_current_command(...)` (line 871)
  - Remove `current_is_interactive = ...` (line 872)
  - Remove `sending_interactive_command = ...` (line 873)
  - Remove `append_exit_marker = not (current_is_interactive or sending_interactive_command)` (line 879)
  - Remove logging blocks (lines 881-892)
  - Remove `shell=config.computer.default_shell` from `send_keys()` call (line 903)
  - Remove `append_exit_marker=append_exit_marker` from `send_keys()` call (line 907)
  - Keep `marker_id` generation for polling

- [x] **SEQUENTIAL** Simplify `create_session()` (line 275)
  - Remove `shell=config.computer.default_shell` from `create_tmux_session()` call
  - tmux will automatically use $SHELL

**BONUS**: Simplified marker_id to always be auto-generated (removed parameter), `send_keys()` now returns `tuple[bool, Optional[str]]` for cleaner API

### Group 3: Remove Lpoll Infrastructure

**Dependencies**: Group 2 (ensure no code references lpoll functions)
**Files**: `teleclaude/core/terminal_bridge.py`, `teleclaude/config.py`, `config.yml.sample`

- [x] **PARALLEL** Delete lpoll code from `terminal_bridge.py`
  - Delete `LPOLL_DEFAULT_LIST` constant (lines 20-71)
  - Delete `_get_lpoll_list()` function (lines 74-77)
  - Delete `is_long_running_command()` function (lines 80-94)
  - Delete `has_command_separator()` function (lines 97-108)
  - Remove command chaining validation from `send_keys()` (lines 237-243)

- [x] **PARALLEL** Remove `lpoll_extensions` from config
  - Remove `lpoll_extensions: list[str]` from `PollingConfig` dataclass (config.py line 96)
  - Remove `"lpoll_extensions": []` from DEFAULT_CONFIG (config.py line 150)
  - Remove lpoll_extensions parsing in `_load_config()` (config.py line 256)
  - Remove `lpoll_extensions: []` line from `config.yml.sample` (line 32)

### Group 4: Simplify Calling Code

**Dependencies**: Group 1 (requires automatic marker decision in `send_keys()`)
**Files**: `teleclaude/core/file_handler.py`, `teleclaude/restart_claude.py`, `teleclaude/core/command_handlers.py`

- [x] **PARALLEL** Remove parameters from `file_handler.py`
  - Remove `append_exit_marker=False` from `send_keys()` call (line 125)
  - Add comment: `# Automatic detection: if process running, no marker`
  - Update to handle tuple return value: `success, _ = await ...`

- [x] **PARALLEL** Remove parameters from `restart_claude.py`
  - Remove `shell=config.computer.default_shell` from `send_keys()` call (line 88)
  - Remove `append_exit_marker=True` from `send_keys()` call (line 90)
  - Add comment: `# Automatic detection: shell ready, marker appended`
  - Update to handle tuple return value: `success, _ = await ...`

- [x] **PARALLEL** Remove shell parameter from `command_handlers.py`
  - Remove `shell = config.computer.default_shell` assignment (line 165)
  - Remove `shell=shell` from `create_tmux_session()` call
  - Remove `shell=config.computer.default_shell` from `send_keys()` call (line 462)
  - Update to handle tuple return value: `success, marker_id = await ...`
  - Remove shell from welcome message

### Group 5: Update Tests

**Dependencies**: Groups 1-4 (all code changes complete)
**Files**: `tests/unit/test_terminal_bridge.py`, `tests/unit/test_file_handler.py`, `tests/integration/*.py`

- [ ] **SEQUENTIAL** Update unit tests in `test_terminal_bridge.py`
  - Delete all `test_*_is_long_running()` tests (lines 149-190)
  - Delete all `test_has_command_separator_*()` tests (lines 194-213)
  - Update `test_append_exit_marker_true()` - remove parameters, mock get_current_command → "zsh"
  - Update `test_append_exit_marker_false()` - mock get_current_command → "vim"
  - Add `test_append_exit_marker_none_command()` - mock get_current_command → None, verify marker appended
  - Update test fixture to not set `default_shell` config (line 17)
  - Mock `_SHELL_NAME` as "zsh" for test consistency

- [ ] **SEQUENTIAL** Update test mocks in `test_file_handler.py`
  - Remove `append_exit_marker` parameter from mock signatures (4 locations: lines 51, 90, 177, 209)
  - Update assertions to not check `append_exit_marker` value
  - Verify file upload tests still pass

- [ ] **SEQUENTIAL** Update integration test mocks
  - Remove `append_exit_marker` from mocks in `test_file_upload.py` (lines 51, 90)
  - Remove `append_exit_marker=True` from `test_polling_restart.py` (lines 60, 80)
  - Remove `append_exit_marker=True` from `test_full_flow.py` (line 170)

- [ ] **SEQUENTIAL** Add new integration tests
  - Add `test_vim_exit_detection()` - start vim, quit, verify immediate marker detection (<2s)
  - Add `test_nested_shell_marker()` - start bash, exit, verify marker fires
  - Add `test_command_chaining_allowed()` - verify `vim && ls` no longer raises ValueError

### Group 6: Documentation Updates

**Dependencies**: Groups 1-5 (implementation and testing complete)
**Files**: `CLAUDE.md`, `config.yml.sample`, `docs/exit-markers.md`

- [ ] **PARALLEL** Update `CLAUDE.md`
  - Remove lpoll list description from "Master Bot Pattern" section
  - Update "Testing Requirements" section to reflect new behavior
  - Add note: "Exit markers now append to ALL commands when shell ready"

- [ ] **PARALLEL** Create `docs/exit-markers.md`
  - Explain shell detection approach
  - Document when markers are appended (shell ready vs process running)
  - Provide troubleshooting guide (check `get_current_command()` logs)
  - List known shells (bash, zsh, sh, fish, dash)

- [ ] **PARALLEL** Archive analysis documents
  - Move `analysis_exit_marker_simplification.md` to `docs/archive/`
  - Move `refactoring_impact_analysis.md` to `docs/archive/`
  - Add note at top: "IMPLEMENTED - See docs/exit-markers.md for current behavior"

### Group 7: Deployment & Validation

**Dependencies**: Groups 1-6 (all changes complete)
**Files**: N/A (deployment tasks)

- [ ] **SEQUENTIAL** Pre-deployment validation
  - Run full test suite: `make test`
  - Verify all tests pass
  - Run linting: `make lint`
  - Verify 10/10 score
  - Manual testing: start vim, quit, verify immediate completion
  - Manual testing: upload file to running vim, verify works

- [ ] **SEQUENTIAL** Deploy to single computer (RasPi)
  - Create git commit with all changes
  - Push to GitHub
  - SSH to RasPi: `ssh -A morriz@raspberrypi.local`
  - Pull changes: `cd ~/apps/TeleClaude && git pull`
  - Restart daemon: `make restart`
  - Monitor logs: `tail -f /var/log/teleclaude.log`
  - Test vim exit detection (should see marker within 1s)
  - Wait 24 hours, monitor for issues

- [ ] **SEQUENTIAL** Deploy to all computers
  - Run `/deploy` command (pushes and deploys to all machines)
  - Verify deployment success on all computers
  - Check logs on each machine for errors
  - Test interactive commands on multiple machines

## Notes

### Critical Implementation Details

1. **$SHELL Detection (Module-Level, Computed Once)**:
   ```python
   import os
   import pwd
   from pathlib import Path

   # User's shell basename, computed once at import
   _SHELL_NAME = Path(os.environ.get("SHELL") or pwd.getpwuid(os.getuid()).pw_shell).name.lower()
   ```

2. **Shell Detection in `send_keys()`**:
   ```python
   # At start of send_keys():
   current_command = await get_current_command(session_name)
   append_exit_marker = not current_command or current_command.lower() == _SHELL_NAME

   # Later in function:
   if append_exit_marker:
       if not marker_id:
           marker_id = hashlib.md5(f"{text}:{time.time()}").hexdigest()[:8]
       command_text = f'{text}; echo "__EXIT__{marker_id}__$?__"'
   else:
       command_text = text
   ```

3. **Remove Parameters Carefully**:
   - `send_keys()` no longer accepts `append_exit_marker` or `shell` parameters
   - `create_tmux_session()` no longer accepts `shell` parameter
   - All callers simplified (no explicit parameters)
   - Tests updated to not pass parameters

4. **Preserve Marker ID for Testing**:
   - Keep `marker_id` parameter in `send_keys()` for test flexibility
   - Auto-generate if not provided
   - Tests can pass explicit marker_id for verification

### Testing Strategy

**Unit Tests** (test logic in isolation):
- `is_shell_ready()` with various inputs
- `send_keys()` behavior with mocked `get_current_command()`

**Integration Tests** (test end-to-end):
- vim exit detection
- Nested shells
- Command chaining
- File upload to running process

**Manual Testing** (before deployment):
- Start vim, quit, verify immediate detection
- Start claude, send message, verify works
- Upload file to running vim, verify works
- Run `bash && ls`, verify chaining allowed

### Rollback Procedure

If critical bug discovered:

```bash
# On affected computer:
git revert <commit-hash>
make restart

# Or globally:
git revert <commit-hash>
git push
# Run /deploy to roll back all machines
```

### Known Edge Cases

**Background Jobs**:
```bash
python script.py &; echo "__EXIT__abc123__$?__"
```
- Marker fires on spawn (exit code 0), not job completion
- This is technically correct (spawn success)
- Document as expected behavior

**Uncommon Shells**:
- fish, nu, elvish might need to be added to shell list
- System defaults to "ready" if unknown (safe)
- Add on user request

**Syntax Errors**:
- Unclosed quotes, incomplete syntax can break marker appending
- Pre-existing issue, not introduced by refactoring
- Consider using `\n` separator instead of `;` in future

## Success Criteria

- [ ] All tests passing (`make test`)
- [ ] No lint errors (`make lint`)
- [ ] Vim exits within 2s (currently 60s)
- [ ] No false "hung up" warnings after interactive commands
- [ ] Command chaining works (`vim && ls`)
- [ ] File upload to running process works
- [ ] No user-reported bugs after 1 week
- [ ] Code reduction: -100+ lines (lpoll + default_shell config)
- [ ] tmux sessions use $SHELL automatically (no config override)

## Estimated Time

- Group 1-4 (Code Changes): 2-3 hours
- Group 5 (Testing): 2-3 hours
- Group 6 (Documentation): 1 hour
- Group 7 (Deployment): 1-2 days (including monitoring)

**Total**: ~1 day implementation + 1-2 days validation

## Review Feedback

- [ ] Review feedback handled (to be checked by `/pr-review-toolkit:review-pr all`)
