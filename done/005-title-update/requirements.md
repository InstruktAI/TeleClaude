# Title Updater Refactoring - Requirements

## Problem Statement

The current title updater has two fundamental issues:

1. **Title reflects agent's last response, NOT user intent** - The LLM summarizer only sees the agent's recent output (tool calls included), so the title describes what Claude did, not what the user asked for.

2. **Title only updates ONCE** - After the first `agent_stop` event sets the title, subsequent stop events skip title updates entirely due to a "Untitled" suffix check.

## Goals (Must-Have)

### G1: Title Captures User Intent

- Title should summarize what the USER wants to accomplish
- Based on the last 2 user messages + their corresponding agent text responses
- **Excludes tool calls** - only include actual text responses from the agent (no tool_use, tool_result blocks)

### G2: Title Updates Every Stop Event

- Every `agent_stop` event should update the session title
- Allows title to evolve as user's focus changes during a session
- No "Untitled" check - always update

### G3: Summary Remains Agent-Focused

- The summary (sent as feedback message) should still describe what the agent just did
- This maintains the existing UX for tracking agent progress

## Non-Goals (Out of Scope)

- Changing the summary format or length
- Modifying title prefix format (`$Computer[project] -`)
- Supporting more than 2 user message + response pairs (cost optimization)
- Caching or deduplication of identical titles

## Technical Constraints

### C1: Token Budget

- Keep LLM input small: only last 2 user messages + their text-only agent responses
- Use existing `UI_MESSAGE_MAX_CHARS` limit for the summary portion

### C2: Transcript Access

- Must parse transcript to extract user messages and corresponding agent responses
- Filter out `tool_use` and `tool_result` blocks - only include `text` type content from assistant

### C3: Backward Compatibility

- The `summarize()` function signature may change, but callers must still work
- Title prefix parsing/preservation must continue working

## Implementation Approach

### Summarizer Changes (`teleclaude/core/summarizer.py`)

1. **New helper function**: `extract_user_intent_context(transcript_path, agent_name, n_messages=2) -> str`

   - Parse transcript to find last N user messages
   - For each user message, extract the immediate text-only agent response (skip tool blocks)
   - Return formatted context string

2. **Updated prompt**: Separate title generation (user intent) from summary generation (agent action)

   ```
   ## Context (recent user requests and agent text responses):
   {user_intent_context}

   ## Latest Agent Output:
   {transcript_tail}

   ## Output:
   1. title (max 50 chars): What the USER is trying to accomplish
   2. summary (1-2 sentences): What the agent just did
   ```

3. **Updated signature**:
   ```python
   async def summarize(
       agent_name: AgentName,
       transcript_path: str,
   ) -> tuple[str | None, str]:
   ```
   (Function internally calls the new helper - no signature change for caller)

### Daemon Changes (`teleclaude/daemon.py`)

1. **Remove "Untitled" check** in `_update_session_title()`:
   - Delete the regex guard: `if not re.search(r"Untitled( \(\d+\))?$", session.title): return`
   - Always update title on every stop event

## Edge Cases

| Case                                | Behavior                                             |
| ----------------------------------- | ---------------------------------------------------- |
| No user messages yet                | Use agent output only (fallback to current behavior) |
| User message without agent response | Include user message, skip missing response          |
| All agent responses are tool-only   | Include user messages only                           |
| Very long user messages             | Truncate to reasonable limit (500 chars each)        |

## Acceptance Criteria

1. After first `agent_stop`: Title reflects user's initial request
2. After subsequent `agent_stop` with different user request: Title updates to new intent
3. Summary still describes agent's latest action (unchanged UX)
4. Tool calls (`tool_use`, `tool_result`) are NOT included in context for title generation
5. All existing tests pass
6. New tests cover: title updates on every stop, user intent extraction, tool filtering
