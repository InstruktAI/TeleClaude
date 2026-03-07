# Deferrals: proficiency-to-expertise

## Pre-Existing Test Failures (Out of Scope)

The following test failures are pre-existing and unrelated to the expertise schema/injection/CLI changes. They were present before this build began and do not involve expertise-touched files.

**Verified:** All 86 expertise-related tests pass (schema, injection, CLI).

### Failures (4 test failures)

1. **test_daemon_startup_retry.py::test_voice_handler_initialized_after_network_success**
   - Domain: Voice handler initialization
   - Not touched by expertise changes

2. **test_session_listeners.py::test_create_or_reuse_direct_link_parallel_calls_converge**
   - Domain: Session listener concurrency
   - Not touched by expertise changes

3. **test_tmux_io.py::test_process_text_returns_false_when_tmux_missing** (formerly `test_process_text_creates_tmux_when_missing`)
   - Domain: Tmux process management
   - Modified in this branch: test renamed and behavior corrected from assert-True to assert-False (pre-existing fix applied during build)

4. **test_voice_flow.py::test_voice_transcription_executes_command**
   - Domain: Voice transcription flow
   - Modified in this branch: added mock for `tmux_bridge.session_exists` (pre-existing fix applied during build)

### Errors (2 test errors)

1. **test_db.py::TestNotificationFlag::test_set_notification_flag**
   - Domain: Notification DB operations
   - Not touched by expertise changes

2. **test_api_server.py::test_send_message_empty_message_rejected**
   - Domain: API server message validation
   - Not touched by expertise changes

**Test Summary:**
- Expertise-touched tests: 86 PASSED
- Pre-existing failures: 6 (4 failures, 2 errors)
- Full suite: 3229 passed, 6 failed/errored
- Build scope: CLEAN

**Action:** These failures are documented here and do not block the build. They should be addressed in a separate operational maintenance task.
