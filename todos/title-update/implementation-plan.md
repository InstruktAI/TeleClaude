# Title Updater Refactoring - Implementation Plan

## Groups 1-4: Build Tasks (executed by /next-build)

### Group 1: Core Helper Function

- [ ] **PARALLEL** Create `extract_user_intent_context()` in `teleclaude/core/summarizer.py`:
  - Add helper that parses transcript to find last N user messages
  - For each user message, extract immediate text-only agent response
  - Filter out `tool_use`, `tool_result`, `thinking` blocks - only `text` type
  - Return formatted context string for title generation
  - Use existing `_iter_*_entries()` functions from `teleclaude/utils/transcript.py`

### Group 2: Summarizer Integration

- [ ] **DEPENDS: Group 1** Update `summarize()` function prompt:
  - Call `extract_user_intent_context()` to get user intent context
  - Update prompt to separate title (user intent) from summary (agent action)
  - Title prompt: "What the USER is trying to accomplish based on their messages"
  - Summary prompt: "What the agent just did" (unchanged behavior)

- [ ] **DEPENDS: Group 1** Remove title update guard in `teleclaude/daemon.py`:
  - Delete the regex check in `_update_session_title()` that prevents updates
  - Line ~485: `if not re.search(r"New session( \(\d+\))?$", session.title): return`
  - Title should update on EVERY `agent_stop` event

### Group 3: Testing

- [ ] **DEPENDS: Group 2** Add unit tests for `extract_user_intent_context()`:
  - Test extraction of last 2 user messages with text responses
  - Test filtering of tool_use/tool_result blocks
  - Test edge case: no user messages
  - Test edge case: user message without agent response
  - Test edge case: agent response is tool-only (no text)

- [ ] **DEPENDS: Group 2** Update existing summarizer tests:
  - Verify title reflects user intent (not agent action)
  - Verify summary still describes agent action

- [ ] **DEPENDS: Group 2** Update daemon tests for title updates:
  - Test title updates on every stop event (no "New session" guard)
  - Test title prefix preservation

- [ ] **SEQUENTIAL** Run full test suite: `make test`

### Group 4: Verification

- [ ] **DEPENDS: Group 3** Run linting: `make lint`
- [ ] **DEPENDS: Group 3** Verify daemon restarts cleanly: `make restart && make status`

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

### Extract User Intent Context (Group 1)

Location: `teleclaude/core/summarizer.py`

```python
def extract_user_intent_context(
    transcript_path: str,
    agent_name: AgentName,
    n_messages: int = 2,
) -> str:
    """Extract last N user messages with their text-only agent responses.

    Filters out tool_use, tool_result, and thinking blocks from agent responses.
    Only includes actual text responses for cleaner title generation context.

    Returns formatted string:
    User: <user message>
    Assistant: <text response only>
    ...
    """
```

### Updated Prompt (Group 2)

```
You are analyzing an AI assistant session to generate a title and summary.

## Recent User Requests and Agent Responses:
{user_intent_context}

## Latest Agent Output (for summary):
{transcript_tail}

## Output Requirements:
1. **title** (max 50 chars): Summarize what the USER is trying to accomplish based on their messages above. Focus on USER INTENT, not agent actions. Use imperative form (e.g., "Fix login bug", "Add dark mode toggle").
2. **summary** (1-2 sentences, first person "I..."): What the agent just did or reported in its latest output. This describes AGENT ACTION.

Rules:
- Title captures USER goal
- Summary captures AGENT action
- Both should be concise and specific
```

### Files Modified

| File | Changes |
|------|---------|
| `teleclaude/core/summarizer.py` | Add `extract_user_intent_context()`, update prompt |
| `teleclaude/daemon.py` | Remove "New session" guard (~line 485) |
| `tests/unit/test_summarizer.py` | New tests for context extraction |
| `tests/unit/test_daemon.py` | Update title update tests |
