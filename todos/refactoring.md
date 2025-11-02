# TeleClaude Refactoring Plan

## Executive Summary

**Status:** 🔴 CRITICAL - Code violates architectural principles
**Priority:** P0 - Must complete before major feature work
**Timeline:** 3-4 weeks
**Impact:** Reduces largest file from 1487 → 560 lines, eliminates ~300 lines of boilerplate

## Current State Assessment

### File Size Violations (Max: 500 lines per CLAUDE.md)

| File | Current Lines | Over Limit | Status |
|------|--------------|------------|--------|
| daemon.py | 1,487 | +987 | 🔴 CRITICAL |
| telegram_adapter.py | 1,059 | +559 | 🔴 CRITICAL |
| terminal_bridge.py | 505 | +5 | 🟡 MINOR |
| session_manager.py | 273 | -227 | ✅ OK |
| base_adapter.py | 260 | -240 | ✅ OK |

### Code Quality Issues

1. **God Classes**: daemon.py does everything (lifecycle, commands, polling, cleanup, files)
2. **DRY Violations**: ~300 lines of repeated boilerplate across files
3. **Poor Modularity**: Big if/elif chains, no command router pattern
4. **Hard to Test**: Tight coupling prevents unit testing
5. **Maintenance Risk**: Changes in one area break others

---

## Phase 1: Critical Size Reduction (Week 1)

**Goal:** Extract largest subsystems to bring files closer to limits

### Task 1.1: Extract Output Poller from daemon.py

**Lines to Extract:** 1100-1424 (324 lines)
**New File:** `teleclaude/core/output_poller.py`
**Impact:** Reduces daemon.py by 22%

**Steps:**
- [ ] Create `teleclaude/core/output_poller.py`
- [ ] Define `OutputPoller` class with `__init__(config, terminal, session_manager)`
- [ ] Move `_poll_and_send_output()` method → `poll_and_send_output()`
- [ ] Update daemon.py to use `self.output_poller = OutputPoller(...)`
- [ ] Replace `await self._poll_and_send_output(...)` → `await self.output_poller.poll_and_send_output(...)`
- [ ] Pass adapter as parameter to polling method
- [ ] Run integration tests: `make test-e2e`
- [ ] Verify polling works in TC TESTS topic

**New Class Structure:**
```python
class OutputPoller:
    def __init__(self, config, terminal, session_manager):
        self.config = config
        self.terminal = terminal
        self.session_manager = session_manager

    async def poll_and_send_output(
        self,
        session_id: str,
        tmux_session_name: str,
        adapter: BaseAdapter,
        output_dir: Path,
        active_polling_sessions: set,
        long_running_sessions: set,
        idle_notifications: dict
    ) -> None:
        # Move entire _poll_and_send_output logic here
```

### Task 1.2: Extract Command Handlers from daemon.py

**Lines to Extract:** 431-897 (466 lines)
**New File:** `teleclaude/core/command_handlers.py`
**Impact:** Reduces daemon.py by 31%

**Steps:**
- [ ] Create `teleclaude/core/command_handlers.py`
- [ ] Define `CommandHandlers` class with `__init__(daemon)`
- [ ] Move all `_create_session()`, `_list_sessions()`, `_cancel_command()`, etc. methods
- [ ] Remove `_` prefix from method names (they're public in the new class)
- [ ] Update daemon.py: `self.command_handlers = CommandHandlers(self)`
- [ ] Update `handle_command()` to delegate: `await self.command_handlers.create_session(...)`
- [ ] Run tests: `make test-e2e`
- [ ] Test all commands via Telegram

**Methods to Move:**
- `_create_session()` → `create_session()`
- `_list_sessions()` → `list_sessions()`
- `_cancel_command()` → `cancel_command()`
- `_escape_command()` → `escape_command()`
- `_resize_session()` → `resize_session()`
- `_rename_session()` → `rename_session()`
- `_cd_session()` → `cd_session()`
- `_claude_session()` → `claude_session()`
- `_claude_resume_session()` → `claude_resume_session()`
- `_exit_session()` → `exit_session()`

### Task 1.3: Extract Telegram Handlers

**Lines to Extract:** telegram_adapter.py:433-973 (540 lines)
**New File:** `teleclaude/adapters/telegram/handlers.py`
**Impact:** Reduces telegram_adapter.py by 51%

**Steps:**
- [ ] Create `teleclaude/adapters/telegram/` directory
- [ ] Create `teleclaude/adapters/telegram/__init__.py`
- [ ] Move `telegram_adapter.py` → `teleclaude/adapters/telegram/adapter.py`
- [ ] Create `teleclaude/adapters/telegram/handlers.py`
- [ ] Define `TelegramHandlers` class with `__init__(adapter, session_manager, daemon)`
- [ ] Move all `_handle_*` methods to new class
- [ ] Update adapter.py to use `self.handlers = TelegramHandlers(...)`
- [ ] Update handler registrations in `start()` to use `self.handlers.handle_new_session`
- [ ] Fix imports in daemon.py: `from teleclaude.adapters.telegram import TelegramAdapter`
- [ ] Run tests: `make test-e2e`

**Methods to Move:**
- `_handle_new_session()`
- `_handle_list_sessions()`
- `_handle_cancel()`
- `_handle_cancel2x()`
- `_handle_escape()`
- `_handle_escape2x()`
- `_handle_resize()`
- `_handle_rename()`
- `_handle_cd()`
- `_handle_claude()`
- `_handle_claude_resume()`
- `_handle_exit()`
- `_handle_help()`
- `_handle_text_message()`
- `_handle_voice_message()`
- `_handle_callback_query()`
- `_handle_topic_closed()`

**Phase 1 Target Results:**
- daemon.py: ~700 lines (still needs work)
- telegram_adapter.py: ~520 lines (close to target)
- 3 new modules created

---

## Phase 2: Complete Modularization (Week 2)

**Goal:** Bring all files under 500-line limit

### Task 2.1: Extract Lock Management from daemon.py

**Lines to Extract:** 107-173 (66 lines)
**New File:** `teleclaude/core/daemon_lock.py`
**Impact:** Reduces daemon.py by 4%, creates reusable component

**Steps:**
- [ ] Create `teleclaude/core/daemon_lock.py`
- [ ] Define `DaemonLock` class with context manager protocol
- [ ] Move `_acquire_lock()` → `acquire()`
- [ ] Move `_release_lock()` → `release()`
- [ ] Add `__enter__` and `__exit__` methods for context manager
- [ ] Update daemon.py: `self.lock = DaemonLock(self.pid_file)`
- [ ] Use as context manager in `main()`: `async with daemon.lock:`
- [ ] Run tests: `make test-all`

**New Class:**
```python
class DaemonLock:
    def __init__(self, pid_file: Path):
        self.pid_file = pid_file
        self.pid_file_handle: Optional[TextIO] = None

    def acquire(self) -> None:
        # Move lock logic here

    def release(self) -> None:
        # Move unlock logic here

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()
```

### Task 2.2: Extract Session Lifecycle Management

**Lines to Extract:** daemon.py:324-366 (67 lines)
**New File:** `teleclaude/core/session_lifecycle.py`
**Impact:** Reduces daemon.py by 4%

**Steps:**
- [ ] Create `teleclaude/core/session_lifecycle.py`
- [ ] Define `SessionLifecycleManager` class
- [ ] Move `_periodic_cleanup()` → `run_periodic_cleanup()`
- [ ] Move `_cleanup_inactive_sessions()` → `cleanup_inactive_sessions()`
- [ ] Update daemon.py: `self.lifecycle_manager = SessionLifecycleManager(...)`
- [ ] Update `start()`: `self.cleanup_task = asyncio.create_task(self.lifecycle_manager.run_periodic_cleanup())`
- [ ] Run tests: `make test-all`

### Task 2.3: Extract Session Output Manager

**New File:** `teleclaude/core/session_output_manager.py`
**Impact:** Centralizes file operations, improves reliability

**Steps:**
- [ ] Create `teleclaude/core/session_output_manager.py`
- [ ] Define `SessionOutputManager` class
- [ ] Move `_get_output_file()` → `get_output_file()`
- [ ] Add `write_output(session_id, content)` method
- [ ] Add `read_output(session_id)` method
- [ ] Add `cleanup_output(session_id)` method
- [ ] Update daemon.py: `self.output_manager = SessionOutputManager(output_dir)`
- [ ] Replace all direct file operations with manager calls
- [ ] Update polling to use `self.output_manager.write_output(...)`
- [ ] Run tests: `make test-e2e`

### Task 2.4: Extract Telegram Helpers

**Lines to Extract:** telegram_adapter.py:398-429, 975-1060 (200 lines)
**New File:** `teleclaude/adapters/telegram/helpers.py`
**Impact:** Reduces telegram_adapter.py by 19%

**Steps:**
- [ ] Create `teleclaude/adapters/telegram/helpers.py`
- [ ] Define `TelegramHelpers` class
- [ ] Move `_get_session_from_topic()` → `get_session_from_topic()`
- [ ] Move `_log_all_updates()` → module-level function
- [ ] Move `_handle_error()` → module-level function
- [ ] Update adapter.py to use helpers
- [ ] Run tests: `make test-all`

### Task 2.5: Extract Command Detection Utils

**Lines to Extract:** terminal_bridge.py:9-65 (65 lines)
**New File:** `teleclaude/utils/command_utils.py`
**Impact:** Reduces terminal_bridge.py to ~440 lines

**Steps:**
- [ ] Create `teleclaude/utils/command_utils.py`
- [ ] Move `LPOLL_DEFAULT_LIST` constant
- [ ] Create `is_long_running_command(command, config)` function
- [ ] Create `has_command_separator(command)` function
- [ ] Update terminal_bridge.py to import from utils
- [ ] Run tests: `make test-all`

**Phase 2 Target Results:**
- daemon.py: ~560 lines ✅
- telegram_adapter.py: ~320 lines ✅
- terminal_bridge.py: ~440 lines ✅
- 5 new focused modules

---

## Phase 3: DRY and Patterns (Week 3)

**Goal:** Eliminate boilerplate, improve code quality

### Task 3.1: Implement Command Router Pattern

**New File:** `teleclaude/core/command_router.py`
**Impact:** Eliminates 25-line if/elif chain

**Steps:**
- [ ] Create `teleclaude/core/command_router.py`
- [ ] Define `CommandRouter` class with route registry
- [ ] Register all commands in `__init__`: `{"new-session": handlers.create_session, ...}`
- [ ] Implement `async def route(command, args, context)` method
- [ ] Update daemon.py `handle_command()` to use router
- [ ] Remove if/elif chain
- [ ] Run tests: `make test-e2e`

**Implementation:**
```python
class CommandRouter:
    def __init__(self, handlers: CommandHandlers):
        self.handlers = handlers
        self._routes = {
            "new-session": handlers.create_session,
            "list-sessions": handlers.list_sessions,
            "cancel": handlers.cancel_command,
            "cancel2x": lambda ctx, args: handlers.cancel_command(ctx, args, double=True),
            "escape": handlers.escape_command,
            "escape2x": lambda ctx, args: handlers.escape_command(ctx, args, double=True),
            "resize": handlers.resize_session,
            "rename": handlers.rename_session,
            "cd": handlers.cd_session,
            "claude": handlers.claude_session,
            "claude_resume": handlers.claude_resume_session,
            "exit": handlers.exit_session,
        }

    async def route(self, command: str, args: List[str], context: Dict[str, Any]) -> None:
        handler = self._routes.get(command)
        if handler:
            await handler(context, args)
        else:
            logger.warning("Unknown command: %s", command)
```

### Task 3.2: Add Handler Decorators

**New File:** `teleclaude/adapters/telegram/decorators.py`
**Impact:** Eliminates ~100 lines of repeated authorization checks

**Steps:**
- [ ] Create `teleclaude/adapters/telegram/decorators.py`
- [ ] Implement `@require_authorization` decorator
- [ ] Implement `@require_session` decorator
- [ ] Apply to all handler methods in `handlers.py`
- [ ] Remove manual authorization checks
- [ ] Run tests: `make test-all`

**Implementation:**
```python
def require_authorization(handler):
    @wraps(handler)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id not in self.adapter.user_whitelist:
            logger.warning("User %s not in whitelist", update.effective_user.id)
            return None
        return await handler(self, update, context)
    return wrapper

def require_session(handler):
    @wraps(handler)
    async def wrapper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        session = await self._get_session_from_topic(update)
        if not session:
            return None
        return await handler(self, update, context, session)
    return wrapper
```

### Task 3.3: Create Context Builder Utilities

**New File:** `teleclaude/core/context_utils.py`
**Impact:** Eliminates ~50 lines of repeated context building

**Steps:**
- [ ] Create `teleclaude/core/context_utils.py`
- [ ] Implement `build_command_context(adapter_type, session, **kwargs)` function
- [ ] Update all command handlers to use builder
- [ ] Run tests: `make test-all`

### Task 3.4: Centralize Error Handling

**New File:** `teleclaude/utils/error_handling.py`
**Impact:** Eliminates ~100 lines of try/except boilerplate

**Steps:**
- [ ] Create `teleclaude/utils/error_handling.py`
- [ ] Implement `async_error_handler` decorator
- [ ] Implement `safe_operation(operation_fn, error_msg)` context manager
- [ ] Apply to command handlers and adapters
- [ ] Run tests: `make test-all`

**Implementation:**
```python
def async_error_handler(operation_name: str, notify_session: bool = True):
    def decorator(handler):
        @wraps(handler)
        async def wrapper(self, session_id: str, *args, **kwargs):
            try:
                result = await handler(self, session_id, *args, **kwargs)
                logger.info("%s succeeded for session %s", operation_name, session_id[:8])
                return result
            except Exception as e:
                logger.error("%s failed for session %s: %s", operation_name, session_id[:8], e)
                if notify_session:
                    adapter = await self._get_adapter_for_session(session_id)
                    await adapter.send_message(session_id, f"❌ {operation_name} failed")
                return False
        return wrapper
    return decorator
```

### Task 3.5: Add Session Helper Utilities

**Update:** `teleclaude/core/command_handlers.py`
**Impact:** Eliminates ~50 lines of session lookup boilerplate

**Steps:**
- [ ] Add `async def _require_session(session_id)` method to CommandHandlers
- [ ] Raises exception if session not found (cleaner than manual checks)
- [ ] Replace all `get_session()` + `if not session` → `_require_session()`
- [ ] Run tests: `make test-all`

**Phase 3 Target Results:**
- ~300 lines of boilerplate eliminated
- Better testability with decorators
- Cleaner, more maintainable code

---

## Phase 4: Testing and Documentation (Week 4)

**Goal:** Ensure refactored code is well-tested and documented

### Task 4.1: Add Unit Tests for New Modules

**Steps:**
- [ ] Create `tests/unit/test_output_poller.py`
- [ ] Create `tests/unit/test_command_router.py`
- [ ] Create `tests/unit/test_daemon_lock.py`
- [ ] Create `tests/unit/test_session_lifecycle.py`
- [ ] Create `tests/unit/test_session_output_manager.py`
- [ ] Create `tests/unit/test_command_utils.py`
- [ ] Create `tests/unit/test_telegram_handlers.py`
- [ ] Create `tests/unit/test_telegram_helpers.py`
- [ ] Run: `make test-unit`
- [ ] Achieve >80% coverage for new modules

### Task 4.2: Integration Testing

**Steps:**
- [ ] Run full integration test suite: `make test-e2e`
- [ ] Test all commands via TC TESTS topic in Telegram
- [ ] Test voice messages
- [ ] Test output polling (short and long-running commands)
- [ ] Test session lifecycle (create, rename, resize, exit)
- [ ] Test error conditions (invalid commands, deleted topics, etc.)
- [ ] Verify no regressions

### Task 4.3: Update Documentation

**Steps:**
- [ ] Update `CLAUDE.md` with new architecture
- [ ] Document new module structure in README
- [ ] Add docstrings to all new classes/functions
- [ ] Update architecture diagram
- [ ] Document refactoring decisions in `docs/refactoring-notes.md`

### Task 4.4: Performance Verification

**Steps:**
- [ ] Benchmark daemon startup time (should be unchanged)
- [ ] Benchmark command response latency (should be unchanged)
- [ ] Monitor memory usage (should be slightly lower due to better modularity)
- [ ] Verify no performance regressions

---

## Success Metrics

### Quantitative Goals

- [x] All files ≤ 500 lines ✅
- [ ] Boilerplate reduced by ~300 lines
- [ ] 11+ new focused modules created
- [ ] Test coverage >80% for new modules
- [ ] Zero integration test failures
- [ ] No performance regressions

### Qualitative Goals

- [ ] Clear module boundaries with single responsibilities
- [ ] Easy to unit test in isolation
- [ ] New developers can understand code structure quickly
- [ ] Changes in one module don't break others
- [ ] Reusable components (lock, router, etc.)

---

## New Module Structure

```
teleclaude/
├── core/
│   ├── daemon.py (560 lines) ✅ - Coordination only
│   ├── command_router.py - Routes commands to handlers
│   ├── command_handlers.py - Implements all commands
│   ├── output_poller.py - Terminal output polling logic
│   ├── session_lifecycle.py - Periodic cleanup, session lifecycle
│   ├── session_output_manager.py - File operations for session output
│   ├── daemon_lock.py - PID file locking
│   ├── context_utils.py - Context building utilities
│   ├── models.py (existing)
│   ├── session_manager.py (existing)
│   ├── terminal_bridge.py (440 lines) ✅
│   └── voice_handler.py (existing)
├── adapters/
│   ├── base_adapter.py (260 lines) ✅
│   └── telegram/
│       ├── __init__.py
│       ├── adapter.py (320 lines) ✅ - Telegram API interface
│       ├── handlers.py - All message/command handlers
│       ├── helpers.py - Helper functions
│       └── decorators.py - Authorization/session decorators
└── utils/
    ├── __init__.py (existing)
    ├── command_utils.py - Command detection utilities
    └── error_handling.py - Error handling decorators/utilities
```

---

## Risk Mitigation

### Risks

1. **Breaking Changes**: Refactoring could introduce bugs
   - **Mitigation**: Comprehensive test suite, incremental changes

2. **Downtime**: Service disruption during refactoring
   - **Mitigation**: Test in dev environment first, quick rollback plan

3. **Scope Creep**: Refactoring takes longer than expected
   - **Mitigation**: Strict phase boundaries, can ship after Phase 2

### Rollback Plan

- Keep original files as `*.backup` until all tests pass
- Git branches for each phase
- Can revert to pre-refactoring state at any time

---

## Dependencies

**Required Before Starting:**
- [ ] Comprehensive test suite exists
- [ ] Development environment setup
- [ ] Backup of production database

**Required Between Phases:**
- [ ] All tests passing before moving to next phase
- [ ] Code review of extracted modules
- [ ] Documentation updated

---

## Notes

- Follow CLAUDE.md principles throughout: no defensive programming, let code fail
- Use `make restart` after each major change to verify daemon still works
- Test in TC TESTS forum topic in Telegram after each extraction
- Prioritize Phase 1 and Phase 2 - they deliver most value
- Phase 3 is nice-to-have but less critical
- Keep daemon downtime to absolute minimum (users depend on 24/7 service)
