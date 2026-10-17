"""The prose a ledger entry renders into the item's log, written in the same transaction as the entry."""

from __future__ import annotations

from typing import Final

from teleclaude.types.workflow_record import LedgerEntry

LOG_HEADER_TEMPLATE: Final = "\n### {at} — {role} · {session} · {act}{bound}\n\n"
LOG_BOUND_TEMPLATE: Final = " ({bound})"
LOG_TEXT_TEMPLATE: Final = "{text}\n"
NO_TEXT: Final = ""


def render_log_entry(entry: LedgerEntry) -> str:
    """The log text of one ledger entry: time, role, session, act and the text, readable as prose."""
    bound = LOG_BOUND_TEMPLATE.format(bound=entry.bound) if entry.bound else NO_TEXT
    header = LOG_HEADER_TEMPLATE.format(
        at=entry.at, role=entry.role or NO_TEXT, session=entry.session_id, act=entry.act.value, bound=bound
    )
    return header + (LOG_TEXT_TEMPLATE.format(text=entry.text) if entry.text else NO_TEXT)
