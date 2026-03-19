"""Shared helpers for YouTube channel tagging flows."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import cast

from teleclaude.core.models import JsonDict

KNOWLEDGE_TAGGING_RULES = (
    "You are a YouTube channel classifier.\n"
    "You may ONLY return tags from the allowed list.\n"
    "IMPORTANT: Use your knowledge! If you recognize the channel or creator, USE that knowledge confidently.\n"
    "Many channels are run by famous people, journalists, educators, or well-known creators - you likely know them.\n"
    "Trust your training data for well-known channels. "
    "Only return n/a for truly obscure channels you don't recognize.\n"
    'If you return ["n/a"], it must be the ONLY tag.\n'
)

WEB_RESEARCH_RULES = (
    "You are a YouTube channel classifier doing research.\n"
    "You may ONLY return tags from the allowed list.\n"
    "DO NOT use prior knowledge or memory. Only use evidence from web search results.\n"
    "Use the web_search tool to find information about each channel.\n"
    "Be conservative: only tag based on clear evidence from search results.\n"
    "If web search finds no useful information, return n/a - do not guess.\n"
    'If you return ["n/a"], it must be the ONLY tag.\n'
)


def build_batch_response_schema(tags: list[str]) -> JsonDict:
    """Build the shared JSON schema for batch channel-tagging responses."""
    tag_enum = sorted(set(tags + ["n/a"]))
    return cast(
        JsonDict,
        {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "channel_id": {"type": "string"},
                            "tags": {"type": "array", "items": {"type": "string", "enum": tag_enum}},
                        },
                        "required": ["channel_id", "tags"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["items"],
            "additionalProperties": False,
        },
    )


def validate_tags(raw_tags: object, allowed: set[str], evidence: str | None) -> list[str] | None:
    """Validate and clean tags from an AI response."""
    if not isinstance(raw_tags, list):
        return None

    cleaned: list[str] = []
    saw_na = False
    for tag in raw_tags:
        value = str(tag).strip()
        if not value:
            continue
        if value == "n/a":
            saw_na = True
            cleaned.append("n/a")
            continue
        if value not in allowed:
            return None
        cleaned.append(value)

    if not cleaned:
        return None
    if saw_na and len(cleaned) > 1:
        return None
    if cleaned != ["n/a"] and (evidence is None or not evidence.strip() or evidence.strip() == "n/a"):
        return None
    return cleaned


def round_robin(agents: Sequence[str]) -> Iterator[str]:
    """Yield agent names forever in round-robin order."""
    index = 0
    while True:
        yield agents[index % len(agents)]
        index += 1
