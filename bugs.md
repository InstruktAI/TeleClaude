# Bugs

## Fixed

### Stop event handling broken - no title/summary, always shows "Work complete!"

**Status:** FIXED (2025-12-10)

**Root cause:**
The summarizer utility (`~/.claude/hooks/teleclaude_utils/summarizer.py`) wasn't loading the `~/.claude/.env` file where API keys are stored. When hooks run via Claude Code, they don't inherit the user's shell environment. Without `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`, the summarizer would silently fall through all API providers and return the default `{"summary": "Work complete!", "title": null}`.

**Fix:**
Added `python-dotenv` to the summarizer's dependencies and `load_dotenv(Path.home() / ".claude" / ".env")` to load API keys at startup.

**Symptoms (now resolved):**
1. Every Stop event posted "Work complete!" feedback instead of the AI-generated summary
2. AI title from the first Stop event was not being created/saved
3. The summary that should come from `[title, summary]` in the Stop event data was not being displayed

**Note:** The feedback message tracking was already working correctly - `send_feedback()` properly adds messages to `pending_feedback_deletions`. The issue was purely that no meaningful content was being generated.
