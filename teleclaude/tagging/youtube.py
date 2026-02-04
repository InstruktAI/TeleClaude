"""YouTube subscription tagging - tags channels in CSV using AI."""

from __future__ import annotations

import asyncio
import csv
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, cast

from aiohttp import ClientSession
from instrukt_ai_logging import get_logger

from teleclaude.core.models import JsonDict
from teleclaude.cron.discovery import Subscriber
from teleclaude.helpers.agent_cli import run_once
from teleclaude.helpers.youtube_helper import (
    SubscriptionChannel,
    _fetch_channel_about_description,
    _safe_get_list,
    _safe_get_str,
)

logger = get_logger(__name__)

# --- Prompts ---

NORMAL_TAGGING_RULES = (
    "You are a YouTube channel classifier.\n"
    "You may ONLY return tags from the allowed list.\n"
    "IMPORTANT: Use your knowledge! If you recognize the channel or creator, USE that knowledge confidently.\n"
    "Many channels are run by famous people, journalists, educators, or well-known creators - you likely know them.\n"
    "Trust your training data for well-known channels. Only return n/a for truly obscure channels you don't recognize.\n"
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


# --- Data Classes ---


@dataclass
class ChannelRow:
    """A channel row from the CSV."""

    channel_id: str
    channel_name: str
    handle: str = ""
    tags: str = ""
    description: str = ""  # Enriched from about page

    def to_dict(self) -> dict[str, str]:
        return {
            "channel_id": self.channel_id,
            "channel_name": self.channel_name,
            "handle": self.handle,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, row: dict[str, str]) -> ChannelRow:
        return cls(
            channel_id=row.get("channel_id", ""),
            channel_name=row.get("channel_name", ""),
            handle=row.get("handle", ""),
            tags=row.get("tags", ""),
        )


@dataclass
class SyncResult:
    """Result of a sync operation."""

    channels_total: int = 0
    channels_updated: int = 0
    channels_skipped: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class TaggingConfig:
    """Configuration for tagging operations."""

    mode: str = "normal+web"  # normal, web, normal+web
    thinking_mode: str = "fast"
    refresh: bool = False
    batch_size: int = 4
    prompt_batch: int = 5
    batch_pause: float = 2.0
    agents: list[str] = field(default_factory=lambda: ["claude"])
    dry_run: bool = False
    verbose: bool = False


# --- CSV Operations ---


def read_csv(path: Path) -> list[ChannelRow]:
    """Read channel rows from CSV."""
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [ChannelRow.from_dict(row) for row in reader]


def write_csv(path: Path, rows: list[ChannelRow]) -> None:
    """Write channel rows to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["channel_id", "channel_name", "handle", "tags"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())


def cleanup_stale_tags(rows: list[ChannelRow], allowed_tags: set[str]) -> int:
    """Remove tags that no longer exist in the allowed list. Returns count modified."""
    modified = 0
    for row in rows:
        if not row.tags or row.tags == "n/a":
            continue
        current = [t.strip() for t in row.tags.split(",") if t.strip()]
        valid = [t for t in current if t in allowed_tags or t == "n/a"]
        if len(valid) != len(current):
            row.tags = ",".join(valid) if valid else "n/a"
            modified += 1
    return modified


# --- Description Enrichment ---


async def _fetch_descriptions(rows: list[ChannelRow]) -> None:
    """Fetch about-page descriptions for rows in parallel."""
    async with ClientSession() as session:
        tasks = []
        for row in rows:
            ch = SubscriptionChannel(
                id=row.channel_id,
                title=row.channel_name,
                handle=row.handle or None,
            )
            tasks.append(_fetch_channel_about_description(session, ch))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for row, result in zip(rows, results):
            if isinstance(result, str) and result:
                row.description = result


def enrich_descriptions(rows: list[ChannelRow]) -> None:
    """Fetch full about-page descriptions for rows."""
    asyncio.run(_fetch_descriptions(rows))


# --- Prompt Building ---


def build_batch_prompt(
    rows: list[ChannelRow],
    tags: list[str],
    *,
    use_web: bool = False,
    retry: bool = False,
) -> str:
    """Build prompt for batch tagging."""
    items = [
        {
            "channel_id": r.channel_id,
            "channel_name": r.channel_name,
            "handle": r.handle,
            "description": r.description if not use_web else "",
        }
        for r in rows
    ]

    rules = WEB_RESEARCH_RULES if use_web else NORMAL_TAGGING_RULES
    retry_note = "Your previous output was invalid. Follow the rules EXACTLY.\n\n" if retry else ""

    if use_web:
        return (
            f"{retry_note}{rules}"
            "Search for each YouTube channel and find what topics they cover.\n"
            "Tag each channel using ONLY the allowed tags based on search evidence.\n\n"
            f"Allowed tags: {tags}\n\n"
            f"Channels (JSON): {json.dumps(items, ensure_ascii=True)}\n\n"
            'Return JSON: {"items": [{"channel_id": "...", "tags": ["tag1"], "evidence": "what you found"}]}'
        )
    else:
        return (
            f"{retry_note}{rules}"
            "Tag each YouTube channel using ONLY the allowed tags.\n"
            "Use BOTH the description AND your prior knowledge about each channel/creator.\n"
            "If you recognize a person or channel from your training, confidently apply relevant tags.\n"
            'Only use ["n/a"] if the channel is truly obscure AND the description gives no clues.\n\n'
            f"Allowed tags: {tags}\n\n"
            f"Channels (JSON): {json.dumps(items, ensure_ascii=True)}\n\n"
            'Return JSON: {"items": [{"channel_id": "...", "tags": ["tag1"], "evidence": "brief reason"}]}'
        )


def build_schema(tags: list[str]) -> JsonDict:
    """Build JSON schema for batch response."""
    tag_enum = sorted(set(tags + ["n/a"]))
    # Cast needed because pyright can't verify recursive JsonValue matches
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


# --- Tag Validation ---


def validate_tags(raw_tags: object, allowed: set[str], evidence: str | None) -> list[str] | None:
    """Validate and clean tags from AI response."""
    if not isinstance(raw_tags, list):
        return None

    cleaned: list[str] = []
    saw_na = False

    for tag in raw_tags:
        val = str(tag).strip()
        if not val:
            continue
        if val == "n/a":
            saw_na = True
            cleaned.append("n/a")
            continue
        if val not in allowed:
            return None
        cleaned.append(val)

    if not cleaned:
        return None
    if saw_na and len(cleaned) > 1:
        return None
    if cleaned != ["n/a"]:
        if evidence is None or not str(evidence).strip() or str(evidence).strip() == "n/a":
            return None

    return cleaned


# --- Agent Interaction ---


def round_robin(agents: list[str]) -> Iterator[str]:
    """Infinite round-robin iterator over agents."""
    idx = 0
    while True:
        yield agents[idx % len(agents)]
        idx += 1


def call_agent(
    agent: str,
    thinking_mode: str,
    prompt: str,
    schema: JsonDict,
    *,
    use_web: bool = False,
) -> JsonDict | None:
    """Call AI agent and return parsed result."""
    try:
        payload = run_once(
            agent=agent,
            thinking_mode=thinking_mode,
            system="You are a helpful assistant.",
            prompt=prompt,
            schema=schema,
            tools="web_search" if use_web else "",
            mcp_tools="",
            timeout_s=60,
        )
        result = payload.get("result", {})
        return result if isinstance(result, dict) else None
    except Exception as e:
        logger.error("agent call failed", agent=agent, error=str(e))
        return None


# --- Batch Processing ---


def process_batch(
    rows: list[ChannelRow],
    config: TaggingConfig,
    tags: list[str],
    allowed_tags: set[str],
    agent_iter: Iterator[str],
    *,
    use_web: bool = False,
    merge_mode: bool = False,
) -> dict[str, str]:
    """Process a batch of rows and return {channel_id: tags_str}."""
    schema = build_schema(tags)
    updates: dict[str, str] = {}

    # Split into prompt batches
    prompt_size = max(1, config.prompt_batch)
    groups = [rows[i : i + prompt_size] for i in range(0, len(rows), prompt_size)]

    def process_group(group: list[ChannelRow], agent: str) -> dict[str, str]:
        """Process a single group."""
        group_results: dict[str, str] = {}
        prompt = build_batch_prompt(group, tags, use_web=use_web)

        result = call_agent(agent, config.thinking_mode, prompt, schema, use_web=use_web)
        if result is None:
            return group_results

        items = _safe_get_list(result, "items")
        by_id = {_safe_get_str(i, "channel_id"): i for i in items if isinstance(i, dict)}

        for row in group:
            item = by_id.get(row.channel_id, {})
            tagged = _safe_get_list(item, "tags")
            evidence = item.get("evidence")
            valid = validate_tags(tagged, allowed_tags, evidence)

            if not valid:
                # Retry once
                retry_prompt = build_batch_prompt([row], tags, use_web=use_web, retry=True)
                retry_result = call_agent(next(agent_iter), config.thinking_mode, retry_prompt, schema, use_web=use_web)
                if retry_result:
                    retry_items = _safe_get_list(retry_result, "items")
                    if retry_items and isinstance(retry_items[0], dict):
                        retry_item = retry_items[0]
                        valid = validate_tags(
                            _safe_get_list(retry_item, "tags"), allowed_tags, retry_item.get("evidence")
                        )
                valid = valid or ["n/a"]

            group_results[row.channel_id] = ",".join(valid)

            if config.verbose:
                logger.debug(
                    "channel tagged",
                    channel_id=row.channel_id,
                    channel_name=row.channel_name,
                    tags=valid,
                )

        return group_results

    # Process groups in parallel
    with ThreadPoolExecutor(max_workers=len(groups)) as executor:
        futures = {executor.submit(process_group, group, next(agent_iter)): group for group in groups}
        for future in as_completed(futures):
            group_results = future.result()
            updates.update(group_results)

    return updates


# --- Main Sync Function ---


def sync_youtube_subscriptions(
    subscriber: Subscriber,
    *,
    mode: str = "normal+web",
    thinking_mode: str = "fast",
    refresh: bool = False,
    batch_size: int = 4,
    prompt_batch: int = 5,
    dry_run: bool = False,
    verbose: bool = False,
) -> SyncResult:
    """
    Sync YouTube subscriptions for a subscriber.

    Args:
        subscriber: The subscriber (global or person) to sync
        mode: Tagging mode (normal, web, normal+web)
        thinking_mode: AI thinking mode (fast, med, slow)
        refresh: Re-evaluate already-tagged channels
        batch_size: Rows per batch
        prompt_batch: Channels per prompt
        dry_run: Don't write changes
        verbose: Print per-row results

    Returns:
        SyncResult with counts
    """
    result = SyncResult()

    # Resolve paths
    csv_filename = "youtube.csv"  # Default
    csv_path = subscriber.subscriptions_dir / csv_filename
    tags = subscriber.tags
    allowed_tags = set(tags)

    if not tags:
        result.errors.append("No tags configured")
        return result

    # Read existing data
    rows = read_csv(csv_path)
    result.channels_total = len(rows)

    if not rows:
        logger.info("no channels to sync", scope=subscriber.scope, name=subscriber.name)
        return result

    # Cleanup stale tags
    stale_count = cleanup_stale_tags(rows, allowed_tags)
    if stale_count > 0 and not dry_run:
        write_csv(csv_path, rows)
        logger.info("cleaned stale tags", count=stale_count)

    # Build config
    config = TaggingConfig(
        mode=mode,
        thinking_mode=thinking_mode,
        refresh=refresh,
        batch_size=batch_size,
        prompt_batch=prompt_batch,
        dry_run=dry_run,
        verbose=verbose,
    )
    agent_iter = round_robin(config.agents)

    # Determine what to process
    if refresh:
        # Re-evaluate already-tagged channels
        pending = [r for r in rows if r.tags and r.tags != "n/a"]
    else:
        # Only untagged channels
        pending = [r for r in rows if not r.tags.strip()]

    if not pending:
        logger.info("nothing to sync", scope=subscriber.scope, name=subscriber.name)
        return result

    # Process in batches
    batch_sz = max(1, batch_size * len(config.agents))
    batches = [pending[i : i + batch_sz] for i in range(0, len(pending), batch_sz)]

    for batch_idx, batch in enumerate(batches, start=1):
        logger.info("batch start", index=batch_idx, total=len(batches), size=len(batch))

        # Enrich with descriptions
        enrich_descriptions(batch)

        # Run normal mode
        if mode in {"normal", "normal+web"}:
            updates = process_batch(
                batch,
                config,
                tags,
                allowed_tags,
                agent_iter,
                use_web=False,
                merge_mode=refresh,
            )
            apply_updates(rows, updates, merge_mode=refresh)
            if not dry_run:
                write_csv(csv_path, rows)
            result.channels_updated += len(updates)

        # Run web mode for n/a results
        if mode in {"web", "normal+web"}:
            na_rows = [r for r in batch if r.tags == "n/a"]
            if na_rows:
                updates = process_batch(
                    na_rows,
                    config,
                    tags,
                    allowed_tags,
                    agent_iter,
                    use_web=True,
                    merge_mode=refresh,
                )
                apply_updates(rows, updates, merge_mode=refresh)
                if not dry_run:
                    write_csv(csv_path, rows)

        logger.info("batch complete", index=batch_idx, total=len(batches), updated=result.channels_updated)

        if batch_idx < len(batches):
            time.sleep(config.batch_pause)

    return result


def apply_updates(
    rows: list[ChannelRow],
    updates: dict[str, str],
    *,
    merge_mode: bool = False,
) -> None:
    """Apply tag updates to rows."""
    for row in rows:
        if row.channel_id not in updates:
            continue

        new_tags = updates[row.channel_id]

        if merge_mode:
            # Merge: add new tags, never remove existing
            existing = set(t.strip() for t in row.tags.split(",") if t.strip() and t.strip() != "n/a")
            incoming = set(t.strip() for t in new_tags.split(",") if t.strip() and t.strip() != "n/a")
            merged = sorted(existing | incoming)
            row.tags = ",".join(merged) if merged else "n/a"
        else:
            row.tags = new_tags
