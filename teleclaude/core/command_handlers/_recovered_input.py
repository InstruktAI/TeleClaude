"""How input a channel recovered after the platform was offline reaches the agent.

A recovered message carries the time it was originally posted. Conversation text is followed by a platform
Notification stating that time, so the agent can tell the message was posted while TeleClaude was away; a
platform command is passed that time as an entry fact of its loader.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from teleclaude.core.dates import format_utc_datetime
from teleclaude.core.injected_text import PlatformTextLabel, platform_control_text

RECOVERED_POSTED_AT_FACT: Final = "posted_while_teleclaude_offline_at"
_NOTICE_SEPARATOR: Final = "\n\n"
_NOTICE_TEMPLATE: Final = "The message above was posted at {posted_at} while TeleClaude was offline."


def recovered_posted_at_stamp(posted_at: datetime) -> str:
    """The posting time of a recovered message, as stated to the agent and kept with the accepted input."""
    return format_utc_datetime(posted_at)


def with_recovered_notice(text: str, posted_at: datetime) -> str:
    """The person's text followed by the platform notification of when it was posted."""
    notice = platform_control_text(
        PlatformTextLabel.NOTIFICATION, _NOTICE_TEMPLATE.format(posted_at=recovered_posted_at_stamp(posted_at))
    )
    return f"{text}{_NOTICE_SEPARATOR}{notice}"


def recovered_entry_facts(posted_at: datetime) -> dict[str, str]:
    """The entry facts that tell a procedure loader its command was posted while TeleClaude was offline."""
    return {RECOVERED_POSTED_AT_FACT: recovered_posted_at_stamp(posted_at)}
