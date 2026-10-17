"""Publication of collected session transcript diagnostics at the command boundary."""

from instrukt_ai_logging import get_logger

from teleclaude.core.runtime_events import publish_runtime_error

logger = get_logger(__name__)


async def publish_transcript_format_mismatches(mismatches: list[tuple[str, str]]) -> None:
    """Publish collected parser diagnostics without changing transcript results."""
    for agent, filename in mismatches:
        try:
            await publish_runtime_error(
                source="transcript_reader",
                message=(
                    f"Transcript parser can't read {agent} session file {filename} — file shape may have changed "
                    "in the agent CLI. Output/summary/title for this session will be empty until the parser is updated."
                ),
                severity="warning",
            )
        except Exception:
            logger.warning("Transcript format error publication failed", exc_info=True)
