# Threaded Output Experiment (Incremental Messages)

## What
Introduce a feature-flagged experiment where agent feedback is delivered as regular conversation turns in Telegram, sourced strictly from the transcript instead of editing a single "output message" pane.

## Why
- Better integration with native Telegram conversation flows.
- High-fidelity mirroring of the real transcript (user inputs + thinking + assistant text).
- Cleaner, non-flashy output by excluding tool calls and results.
- **Headless Precedent:** Headless sessions already render via the transcript; this is the logical first path for the experiment.

## Requirements
- **Feature Flag:** `ui.experiments.incremental_threaded_output: bool = False`.
- **Source of Truth:** Strictly use the session transcript (native log files). Do NOT use `last_message_sent` from the DB.
- **Formatting & Order:**
    - User message: Plain text.
    - Assistant `thinking` block: *Italic text*.
    - Assistant text block: Plain text.
- **Exclusions:** Remove all tool calls and tool results from the threaded feed.
- **Set and Forget:** No complex state tracking or message counts in the DB; just dispatch the new turns to the UI adapter as they appear in the transcript.

## Plan

### Phase 1: Infrastructure
- [ ] Move experiment flag to `UIConfig` in `teleclaude/config.py`.
- [ ] Add `send_threaded_turns(session, turns)` to `AdapterClient` contract.

### Phase 2: Ordered Transcript Extraction
- [ ] Enhance `teleclaude/utils/transcript.py` to yield an ordered list of conversational turns (User, Thinking, Text).
- [ ] Implement filtering logic to omit tool use/results while preserving the narrative flow.

### Phase 3: Headless-First Integration
- [ ] Refactor `HeadlessSnapshotService` to dispatch individual turns via `send_threaded_turns` when the flag is enabled.
- [ ] Ensure the legacy "single pane" logic is bypassed when in threaded mode.

### Phase 4: Interactive Sync
- [ ] Update `AgentCoordinator.handle_stop` to trigger a transcript-driven sync of the latest turns.
- [ ] Update `handle_user_prompt_submit` to ensure the user turn is mirrored first to maintain thread integrity.

### Phase 5: Verification
- [ ] **Unit Tests:** Verify ordered turn extraction across Claude/Gemini/Codex with thinking/text interleaving.
- [ ] **Integration Tests:** Verify no turn duplication when multiple hook events arrive.
- [ ] **Regression Tests:** Verify legacy single-pane mode is untouched when flag is off.

## See also
- docs/project/spec/threaded-output-experiment.md (to be created)
- concept/ai-to-ai-coordination
