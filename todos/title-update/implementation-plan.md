# Title Updater Refactoring - Implementation Plan

## Groups 1-4: Build Tasks (executed by /next-build)

### Group 1: Core Helper Function

- [x] **PARALLEL** Create `extract_recent_exchanges()` in `teleclaude/core/summarizer.py`:
  - Parse transcript to find last N user messages + their agent text responses
  - Filter out `tool_use`, `tool_result`, `thinking` blocks - only `text` type content
  - Return formatted string of recent exchanges for LLM prompt
  - Use existing `_iter_*_entries()` functions from `teleclaude/utils/transcript.py`

### Group 2: Summarizer Integration

- [x] **DEPENDS: Group 1** Update `summarize()` function prompt:
  - Call `extract_recent_exchanges()` to get recent user↔agent exchanges
  - Update prompt to generate BOTH title and summary from same context
  - Title: "What the USER is trying to accomplish" (derived from user messages)
  - Summary: "What the agent just did" (derived from agent text responses)

- [x] **DEPENDS: Group 1** Remove title update guard in `teleclaude/daemon.py`:
  - Delete the regex check in `_update_session_title()` that prevents updates
  - Line ~485: `if not re.search(r"New session( \(\d+\))?$", session.title): return`
  - Title should update on EVERY `agent_stop` event

### Group 3: Testing

- [x] **DEPENDS: Group 2** Add unit tests for `extract_recent_exchanges()`:
  - Test extraction of last 2 user messages with text responses
  - Test filtering of tool_use/tool_result blocks
  - Test edge case: no user messages
  - Test edge case: user message without agent response
  - Test edge case: agent response is tool-only (no text)

- [x] **DEPENDS: Group 2** Update existing summarizer tests:
  - Verify title reflects user intent (not agent action)
  - Verify summary still describes agent action

- [x] **DEPENDS: Group 2** Update daemon tests for title updates:
  - Test title updates on every stop event (no "New session" guard)
  - Test title prefix preservation

- [x] **SEQUENTIAL** Run full test suite: `make test`

### Group 4: Verification

- [x] **DEPENDS: Group 3** Run linting: `make lint`
- [x] **DEPENDS: Group 3** Verify daemon restarts cleanly: `make restart && make status`

## Groups 5-6: Review & Finalize (handled by other commands)

### Group 5: Review

- [ ] **SEQUENTIAL** Review created (-> /next-review)
- [ ] **SEQUENTIAL** Review feedback handled

### Group 6: Merge & Deploy

- [ ] **SEQUENTIAL** Tests pass locally
- [ ] **SEQUENTIAL** Merged to main and pushed
- [ ] **SEQUENTIAL** Deployment verified
- [ ] **SEQUENTIAL** Roadmap item marked complete

## Implementation Details

### Extract Recent Exchanges (Group 1)

Location: `teleclaude/core/summarizer.py`

```python
def extract_recent_exchanges(
    transcript_path: str,
    agent_name: AgentName,
    n_exchanges: int = 2,
) -> str:
    """Extract last N user messages with their text-only agent responses.

    Filters out tool_use, tool_result, and thinking blocks from agent responses.
    Only includes actual text responses.

    Returns formatted string:
    User: <user message>
    Assistant: <text response only>
    ...
    """
```

### Updated Prompt (Group 2)

```
Analyze this AI assistant session to generate a title and summary.

## Recent Exchanges:
{exchanges}

## Output:
1. **title** (max 50 chars): What the USER is trying to accomplish. Focus on user intent, not agent actions. Use imperative form (e.g., "Fix login bug", "Add dark mode").
2. **summary** (1-2 sentences, first person "I..."): What the agent just did based on its responses above.
```

### Files Modified

| File | Changes |
|------|---------|
| `teleclaude/core/summarizer.py` | Add `extract_recent_exchanges()`, update prompt |
| `teleclaude/daemon.py` | Remove "New session" guard (~line 485) |
| `tests/unit/test_summarizer.py` | New tests for exchange extraction |
| `tests/unit/test_daemon.py` | Update title update tests |