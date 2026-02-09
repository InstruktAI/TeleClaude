# Rolling Session Titles — Requirements

## R1: Rolling title prompt

Add `_build_rolling_title_prompt(user_inputs: list[str])` to `teleclaude/core/summarizer.py`.

- Takes a list of recent user inputs (last 3).
- Prompt instructs the model to synthesize a title that captures the session's current direction — not just the latest message, but the trajectory.
- Same output schema as existing (`{title, summary}`), same constraints (max 7 words, max 70 chars, imperative form).
- Add `summarize_session_direction(user_inputs: list[str])` wrapper that calls `_call_summarizer` with the rolling prompt.

## R2: Re-summarize title on every user input

Modify `handle_user_prompt_submit` in `teleclaude/core/agent_coordinator.py`.

- Remove the `if session.title == "Untitled"` one-shot guard.
- On every real user input (non-checkpoint):
  - If `session.native_log_file` and `session.active_agent` are available, extract last 3 user messages via `_extract_last_message_by_role(transcript_path, agent_name, "user", count=3)`.
  - If 3+ messages found: call `summarize_session_direction` with the extracted messages.
  - If fewer than 3 (early session): fall back to existing `summarize_user_input(payload.prompt)`.
  - Only write the new title to DB if it differs from `session.title`.

## R3: Reset output message on any title change

Modify `_handle_session_updated` in `teleclaude/adapters/ui_adapter.py`.

- When a title field change is detected (already handled for display title sync), also clear `output_message_id` for the session.
- This forces the next polling cycle to send a new output message instead of editing the existing one.
- The new message makes the Telegram topic float to the top and scrolls old content out of sight.

## R4: Verification

- Existing summarizer tests cover the `_call_summarizer` path; add unit tests for the new rolling prompt builder.
- Add unit test verifying that `handle_user_prompt_submit` calls rolling summarization when 3+ user messages exist.
- Add unit test verifying that `_handle_session_updated` clears output_message_id on title change.

## Files to change

| File                                   | Change                                                               |
| -------------------------------------- | -------------------------------------------------------------------- |
| `teleclaude/core/summarizer.py`        | Add `_build_rolling_title_prompt`, `summarize_session_direction`     |
| `teleclaude/core/agent_coordinator.py` | Modify `handle_user_prompt_submit` to always re-summarize            |
| `teleclaude/adapters/ui_adapter.py`    | Clear output_message_id on title change in `_handle_session_updated` |
| `tests/unit/test_agent_coordinator.py` | Test rolling title trigger logic                                     |
| `tests/unit/test_ui_adapter.py`        | Test output message reset on title change                            |
