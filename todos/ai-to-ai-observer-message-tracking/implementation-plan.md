# AI-to-AI Observer Message Tracking - Implementation Plan

> **Requirements**: todos/ai-to-ai-observer-message-tracking/requirements.md
> **Status**: 🚧 Ready to Implement
> **Created**: 2025-11-28

## Implementation Groups

**IMPORTANT**: Tasks within each group CAN be executed in parallel. Groups must be executed sequentially.

### Group 1: Investigation & Diagnosis

_These tasks investigate the current state and identify issues_

- [ ] **PARALLEL** Create test script to verify `_get_adapter_key()` returns correct adapter type
- [ ] **PARALLEL** Start live AI-to-AI session (MozBook → RasPi4) and capture session IDs
- [ ] **PARALLEL** Add debug logging to `ui_adapter.py:send_output_update()` to track message_id flow
- [ ] **DEPENDS: Start session** Check RasPi4 database for `adapter_metadata.telegram.output_message_id`
- [ ] **DEPENDS: Start session** Monitor RasPi4 logs for message_id storage/retrieval events
- [ ] **DEPENDS: Start session** Observe RasPi4 Telegram behavior (one message vs multiple)

### Group 2: Bug Fixes (if issues found)

_These tasks fix identified issues - skip if investigation shows no bugs_

- [ ] **PARALLEL** Fix `_get_adapter_key()` if adapter type detection is wrong
- [ ] **PARALLEL** Fix `send_output_update()` if message_id not being stored in `adapter_metadata`
- [ ] **PARALLEL** Fix adapter_client broadcast logic if observers not receiving updates
- [ ] **DEPENDS: Fixes applied** Restart daemon with `/deploy` and verify fixes work

### Group 3: Testing & Verification

_These tasks verify the fix works correctly_

- [ ] **PARALLEL** Start new AI-to-AI session and verify single message editing
- [ ] **PARALLEL** Verify `adapter_metadata.telegram.output_message_id` is stored correctly
- [ ] **PARALLEL** Run existing test suite to ensure no regressions: `make test`
- [ ] **DEPENDS: Group 2** Add integration test for observer message tracking

### Group 4: Documentation & Polish

_These tasks document the verified behavior_

- [ ] **PARALLEL** Document observer message tracking behavior in `todos/{slug}/verification-results.md`
- [ ] **PARALLEL** Update logging to include adapter type in debug messages (if needed)
- [ ] **DEPENDS: Group 3** Run `make format && make lint && make test`

### Group 5: Review & Finalize

_These tasks must run sequentially_

- [ ] Review created (automated via `/pr-review-toolkit:review-pr all`)
- [ ] Review feedback handled (automated by spawned agents)

### Group 6: Deployment

_These tasks must run sequentially_

- [ ] Test locally with `make restart && make status`
- [ ] Switch to main: `cd ../.. && git checkout main`
- [ ] Merge worktree branch: `git merge ai-to-ai-observer-message-tracking`
- [ ] Push and deploy: `/deploy`
- [ ] Verify deployment on all computers (MozBook, RasPi4)
- [ ] Cleanup worktree: `/remove_worktree_prompt ai-to-ai-observer-message-tracking`

## Task Markers

- `**PARALLEL**`: Can execute simultaneously with other PARALLEL tasks in same group
- `**DEPENDS: GroupName**`: Requires all tasks in GroupName to complete first
- `**SEQUENTIAL**`: Must run after previous task in group completes

## Implementation Notes

### Key Design Decisions

- **Verification-first approach**: We start with investigation to understand current state before making changes
- **Conditional fixes**: Group 2 tasks only apply if bugs are found during investigation
- **Live testing**: Use real AI-to-AI sessions with RasPi4 to verify observer behavior
- **Database inspection**: Check `adapter_metadata` structure directly to verify storage

### Potential Blockers

- RasPi4 may be offline (check with `teleclaude__list_computers`)
- Database structure may not match expectations (need to inspect actual data)
- Redis output stream may not be distributing to observers correctly
- Telegram API rate limiting may affect message editing verification

### Files to Create/Modify

**New Files**:
- `todos/ai-to-ai-observer-message-tracking/verification-results.md` - Document findings from investigation
- `tests/integration/test_observer_message_tracking.py` - Integration test for observer message editing (if needed)
- `scripts/test_adapter_key.py` - Temporary script to test `_get_adapter_key()` (delete after verification)

**Modified Files** (if bugs found):
- `teleclaude/adapters/ui_adapter.py` - Fix `_get_adapter_key()` or `send_output_update()` if issues detected
- `teleclaude/core/adapter_client.py` - Fix broadcast logic if observers not receiving updates
- `teleclaude/adapters/redis_adapter.py` - Fix output stream listener if distribution broken

## Success Verification

Before marking complete, verify all requirements success criteria:

- [ ] **Live Verification**: Start AI-to-AI session MozBook → RasPi4, confirm RasPi4 Telegram edits ONE message (not multiple)
- [ ] **Database Verification**: Confirm `adapter_metadata.telegram.output_message_id` is stored in remote session
- [ ] **Log Verification**: Logs show message_id storage and retrieval events
- [ ] **Regression Check**: Existing Telegram sessions (non-observer) still work correctly
- [ ] **Code Quality**: All tests pass (`make test && make lint`)

## Completion

- [ ] All task groups completed
- [ ] Success criteria verified
- [ ] Mark roadmap item as complete (N/A - not in roadmap, this is a verification task)

---

**Usage with /next-work**: The next-work command will execute tasks group by group, running PARALLEL tasks simultaneously when possible.
