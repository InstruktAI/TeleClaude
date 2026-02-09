# Rolling Session Titles

## Problem

Session titles are summarized once from the first user input and never updated. As the session evolves, the title becomes stale and no longer reflects what the session is actually about.

Additionally, when the title changes, the Telegram topic should visually refresh — the old output message stays pinned and the topic doesn't float to the top. This creates a stale UX where you have to scroll to find active sessions.

## Intended Outcome

1. **Rolling title re-summarization**: After 3+ user messages exist in the transcript, re-summarize the title based on the last 3 user inputs on every `user_prompt_submit`. The title reflects where the session is heading, not where it started.

2. **Dedicated rolling prompt**: The initial single-input prompt works fine for one message. A separate prompt synthesizes multiple user inputs into a directional title (what the session is evolving toward).

3. **Output message reset on any title change**: Whenever the title changes (including the initial set), clear `output_message_id` so the next polling cycle sends a new output message. This makes the topic float to the top in Telegram and scrolls old content out of sight.

## Key Constraints

- No new DB tables. User input history comes from native transcript files via existing `_extract_last_message_by_role(transcript_path, agent_name, "user", count=3)`.
- Title updates are best-effort (failures must not break the session).
- The rolling prompt must be cheap (Haiku / GPT-5-nano, same as current summarizer).
- Only update the title if the new title is actually different from the current one.
