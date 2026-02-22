# Implementation Plan: ui-adapter-pre-respond-trigger

## Overview

Add a `send_typing_indicator` hook to the UI adapter hierarchy, called from `_dispatch_command` before executing the user's command. Each platform adapter overrides with its native typing API. The call is fire-and-forget — failures are logged but never block message processing.

## Phase 1: Core Changes

### Task 1.1: Add base method and call site in UiAdapter

**File(s):** `teleclaude/adapters/ui_adapter.py`

- [ ] Add `async def send_typing_indicator(self, session: "Session") -> None` as a no-op default method (below `_pre_handle_user_input`).
- [ ] In `_dispatch_command`, after the `pre_handle_command` call and before `result = await handler()`, insert a guarded call:
  ```python
  # Send typing indicator (fire-and-forget, never blocks processing)
  if session.lifecycle_status != "headless":
      try:
          await self.send_typing_indicator(session)
      except Exception:
          logger.debug("Typing indicator failed for session %s", session.session_id[:8], exc_info=True)
  ```

### Task 1.2: Implement in TelegramAdapter

**File(s):** `teleclaude/adapters/telegram_adapter.py`

- [ ] Import `ChatAction` from `telegram.constants`.
- [ ] Override `send_typing_indicator`:
  ```python
  async def send_typing_indicator(self, session: "Session") -> None:
      topic_id = session.get_metadata().get_ui().get_telegram().topic_id
      if not topic_id:
          return
      await self.bot.send_chat_action(
          chat_id=self.supergroup_id,
          action=ChatAction.TYPING,
          message_thread_id=topic_id,
      )
  ```

### Task 1.3: Implement in DiscordAdapter

**File(s):** `teleclaude/adapters/discord_adapter.py`

- [ ] Override `send_typing_indicator`:
  ```python
  async def send_typing_indicator(self, session: "Session") -> None:
      discord_meta = session.get_metadata().get_ui().get_discord()
      if discord_meta.thread_id is None:
          return
      thread = await self._get_channel(discord_meta.thread_id)
      if thread and hasattr(thread, "trigger_typing"):
          await thread.trigger_typing()
  ```

---

## Phase 2: Validation

### Task 2.1: Tests

- [ ] Add unit test in `tests/unit/` verifying `_dispatch_command` calls `send_typing_indicator` when `lifecycle_status != "headless"`.
- [ ] Add unit test verifying `send_typing_indicator` is NOT called for headless sessions.
- [ ] Add unit test verifying that an exception in `send_typing_indicator` does not prevent the command handler from executing.
- [ ] Run `make test`

### Task 2.2: Quality Checks

- [ ] Run `make lint`
- [ ] Verify no unchecked implementation tasks remain

---

## Phase 3: Review Readiness

- [ ] Confirm requirements are reflected in code changes
- [ ] Confirm implementation tasks are all marked `[x]`
- [ ] Document any deferrals explicitly in `deferrals.md` (if applicable)
