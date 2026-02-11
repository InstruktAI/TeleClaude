# Implementation Plan - TTS Fallback Saturation

## User Review Required

> [!IMPORTANT]
> This plan modifies core TTS logic and command handling.

- **Proposed Changes**: Update `teleclaude/tts/manager.py` to filter fallback voices and `teleclaude/core/command_handlers.py` to remove eager assignment.

## Proposed Changes

### TTS Manager

#### [ ] Update `trigger_event` logic

- **File**: `teleclaude/tts/manager.py`
- **Function**: `trigger_event`
- **Changes**:
  1.  Call `voices_in_use = await db.get_voices_in_use()` at the beginning of the function (or before the loop).
  2.  Inside the priority loop (where fallback services are added):
      - Retrieve `service_cfg.voices`.
      - Filter `available_voices = [v for v in service_cfg.voices if (service_name, v.voice_id or v.name) not in voices_in_use]`
      - If `available_voices` is empty, `continue` (skip this service).
      - If available, `random_voice = random.choice(available_voices)`.
      - Append to `service_chain`.

### Command Handlers

#### [ ] Remove eager voice assignment

- **File**: `teleclaude/core/command_handlers.py`
- **Function**: `create_session`
- **Changes**:
  - Remove the following block:
    ```python
    # Assign random voice for TTS
    voice = await get_random_voice()
    if voice:
        await db.assign_voice(session_id, voice)
    ```
  - This ensures voice assignment is deferred until `TTSManager.trigger_event` is called.

## Verification Plan

### Automated Tests

- Since TTS requires API keys and specific environment setups, unit tests are difficult to add without extensive mocking.
- We will rely on manual verification and code review.

### Manual Verification

- **Scenario**: Simulate saturation.
  - Temporarily configure a provider (e.g., `dummy_provider`) with 1 voice.
  - Start Session A. It should get that voice (upon first TTS event).
  - Start Session B. It should _not_ get that voice as a fallback if its primary fails.
- **Log Verification**:
  - Check logs for "All %s voices in use, skipping fallback service" (add this log line).
  - Verify `create_session` logs no longer show "Assigned voice..." messages.
