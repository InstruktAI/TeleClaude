"""Session summarizer service.

Generates summaries and titles from session logs using LLMs.
"""

import logging
import os
from pathlib import Path

from teleclaude.core.agent_parsers import ClaudeParser, CodexParser, GeminiParser
from teleclaude.core.db import db
from teleclaude.core.parsers import LogParser

# Optional imports for LLM clients
try:
    from anthropic import AsyncAnthropic  # type: ignore
except ImportError:
    AsyncAnthropic = None  # type: ignore

try:
    from openai import AsyncOpenAI  # type: ignore
except ImportError:
    AsyncOpenAI = None  # type: ignore

logger = logging.getLogger(__name__)


class SessionSummarizer:
    """Service to summarize session logs."""

    def __init__(self) -> None:
        self.parsers: dict[str, LogParser] = {
            "claude": ClaudeParser(),
            "codex": CodexParser(),
            "gemini": GeminiParser(),
        }

    async def summarize_session(self, session_id: str) -> dict[str, str | None]:
        """Generate summary and title for a session.

        Args:
            session_id: TeleClaude session ID

        Returns:
            Dict with "summary" and "title" keys.
        """
        # Get session info
        ux_state = await db.get_ux_state(session_id)
        if not ux_state.native_log_file:
            logger.warning("No native_log_file for session %s, skipping summary", session_id[:8])
            return {"summary": "Work complete!", "title": None}

        agent_name = ux_state.active_agent or "claude"
        parser = self.parsers.get(agent_name)

        if not parser:
            logger.warning("No parser for agent %s", agent_name)
            return {"summary": "Work complete!", "title": None}

        # Extract content
        log_path = Path(ux_state.native_log_file)
        if not log_path.exists():
            return {"summary": "Work complete!", "title": None}

        content = parser.extract_last_turn(log_path)
        if not content:
            return {"summary": "Work complete!", "title": None}

        # Generate summary via LLM
        return await self._generate_summary(content)

    async def _generate_summary(self, content: str) -> dict[str, str | None]:
        """Generate summary using available LLM API."""
        prompt = f"""Summarize what an AI assistant reported in its last messages. Write for humans tracking progress.

Rules:
- First person ("I...")
- 1-2 sentences
- Accurately reflect what the AI said it did or observed
- Preserve the subject
- Also provide a short title (max 50 chars)

Format:
SUMMARY: <your summary>
TITLE: <short title>

AI's recent messages:
{content}"""

        # Try Anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if api_key and AsyncAnthropic:
            try:
                client = AsyncAnthropic(api_key=api_key)
                response = await client.messages.create(
                    model="claude-3-5-haiku-20241022",
                    max_tokens=200,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.content[0].text  # type: ignore
                return self._parse_response(text)
            except Exception as e:
                logger.error("Anthropic summary failed: %s", e)

        # Try OpenAI
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key and AsyncOpenAI is not None:
            try:
                client = AsyncOpenAI(api_key=openai_key)
                response = await client.chat.completions.create(
                    model="gpt-4o-mini",
                    max_tokens=200,
                    messages=[{"role": "user", "content": prompt}],
                )
                text = response.choices[0].message.content or ""  # type: ignore[misc]
                return self._parse_response(text)
            except Exception as e:
                logger.error("OpenAI summary failed: %s", e)

        return {"summary": "Work complete!", "title": None}

    def _parse_response(self, text: str) -> dict[str, str | None]:
        summary = "Work complete!"
        title = None
        for line in text.strip().split("\n"):
            if line.startswith("SUMMARY:"):
                summary = line[8:].strip()
            elif line.startswith("TITLE:"):
                title = line[6:].strip()[:50]
        return {"summary": summary, "title": title}


# Singleton
summarizer = SessionSummarizer()
