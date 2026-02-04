"""Sync YouTube subscriptions into CSV and tag new rows."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

import yaml
from aiohttp import ClientSession
from instrukt_ai_logging import configure_logging, get_logger

from teleclaude.core.models import JsonDict
from teleclaude.helpers.agent_cli import run_once
from teleclaude.helpers.youtube_helper import (
    SubscriptionChannel,
    _fetch_channel_about_description,
    _safe_get_list,
    _safe_get_str,
    youtube_subscriptions,
)

STRICT_TAGGING_RULES = (
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


def _load_tags(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"Missing config: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    tags = data.get("interests", {}).get("tags", [])
    if not tags:
        raise ValueError(f"Missing interests.tags in config: {path}")
    return [str(t) for t in tags]


def _cleanup_stale_tags(rows: list[dict[str, str]], allowed_tags: set[str]) -> int:
    """Remove tags that no longer exist in the allowed list. Returns count of rows modified."""
    modified = 0
    for row in rows:
        current = row.get("tags", "")
        if not current or current == "n/a":
            continue
        current_tags = [t.strip() for t in current.split(",") if t.strip()]
        valid_tags = [t for t in current_tags if t in allowed_tags or t == "n/a"]
        if len(valid_tags) != len(current_tags):
            row["tags"] = ",".join(valid_tags) if valid_tags else "n/a"
            modified += 1
    return modified


def _ensure_csv(path: Path) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["channel_id", "channel_name", "handle", "tags"],
        )
        writer.writeheader()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [dict(r) for r in reader]


def _write_csv(path: Path, rows: Iterable[dict[str, str]]) -> None:
    fieldnames = ["channel_id", "channel_name", "handle", "tags"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _call_youtube_helper() -> list[dict[str, str | None]]:
    """Fetch subscription list (no enrichment - that happens per-batch later)."""

    async def _fetch() -> list[dict[str, str | None]]:
        results = await youtube_subscriptions(list_channels=True, get_about_descriptions=False)
        # When list_channels=True, results are SubscriptionChannel objects
        return [
            {
                "id": ch.id,
                "title": ch.title,
                "handle": getattr(ch, "handle", None),
                "url_suffix": getattr(ch, "url_suffix", None),
                "description": getattr(ch, "description", None),
                "subscribers": getattr(ch, "subscribers", None),
            }
            for ch in results
        ]

    return asyncio.run(_fetch())


def _enrich_batch_descriptions(rows: list[dict[str, str]]) -> None:
    """Fetch full about-page descriptions for a batch of rows in parallel."""

    async def _fetch_all() -> None:
        async with ClientSession() as session:
            tasks = []
            for row in rows:
                ch = SubscriptionChannel(
                    id=row.get("channel_id", ""),
                    title=row.get("channel_name", ""),
                    handle=row.get("handle"),
                )
                tasks.append(_fetch_channel_about_description(session, ch))
            results = await asyncio.gather(*tasks)
            for row, desc in zip(rows, results):
                if desc:
                    row["_description"] = desc

    asyncio.run(_fetch_all())


def _round_robin(agents: list[str]) -> Iterable[str]:
    idx = 0
    while True:
        yield agents[idx % len(agents)]
        idx += 1


def _call_agent_cli(
    agent: str,
    thinking_mode: str,
    prompt: str,
    schema: JsonDict,
    logger: logging.Logger,
    *,
    debug: bool = False,
    tools: str | None = None,
    mcp_tools: str | None = "",
) -> JsonDict | None:
    if debug:
        print(json.dumps({"debug_prompt": prompt}))
    try:
        payload = run_once(
            agent=agent,
            thinking_mode=thinking_mode,
            system="You are a helpful assistant.",
            prompt=prompt,
            schema=schema,
            debug_raw=debug,
            tools=tools,
            mcp_tools=mcp_tools,
            timeout_s=60,
        )
        if debug:
            print(json.dumps({"debug_result": payload.get("result", {})}))
        result = payload.get("result", {})
        if isinstance(result, dict):
            return result
    except Exception as exc:
        logger.error("tag error: %s (agent=%s)", str(exc), agent)
        return None
    return None


def _build_prompt(row: dict[str, str], tags: list[str], *, retry: bool = False) -> str:
    desc_json = json.dumps(row.get("_description", ""), ensure_ascii=True)
    retry_note = "Your previous output was invalid. Follow the rules EXACTLY.\n\n" if retry else ""
    return (
        f"{retry_note}{STRICT_TAGGING_RULES}"
        "Tag this YouTube channel using ONLY the allowed tags.\n"
        "Use BOTH the description AND your prior knowledge about the channel/creator.\n"
        "If you recognize this person or channel from your training, confidently apply relevant tags.\n"
        'Only return ["n/a"] if the channel is truly obscure AND the description gives no clues.\n\n'
        f"Allowed tags: {tags}\n\n"
        f"Channel name: {row.get('channel_name', '')}\n"
        f"Handle: {row.get('handle', '')}\n"
        f"Description (JSON string): {desc_json}\n\n"
        'Return JSON: {"tags": ["tag1", "tag2"], "evidence": "brief reason"}\n'
        'If truly unknown, return {"tags": ["n/a"], "evidence": "n/a"}.'
    )


def _build_batch_prompt(
    rows: list[dict[str, str]],
    tags: list[str],
    *,
    retry: bool = False,
) -> str:
    items = []
    for row in rows:
        items.append(
            {
                "channel_id": row.get("channel_id", ""),
                "channel_name": row.get("channel_name", ""),
                "handle": row.get("handle", ""),
                "description": row.get("_description", ""),
            }
        )
    retry_note = "Your previous output was invalid. Follow the rules EXACTLY.\n\n" if retry else ""
    return (
        f"{retry_note}{STRICT_TAGGING_RULES}"
        "Tag each YouTube channel using ONLY the allowed tags.\n"
        "Use BOTH the description AND your prior knowledge about each channel/creator.\n"
        "If you recognize a person or channel from your training, confidently apply relevant tags.\n"
        'Only use ["n/a"] if the channel is truly obscure AND the description gives no clues.\n\n'
        f"Allowed tags: {tags}\n\n"
        f"Channels (JSON): {json.dumps(items, ensure_ascii=True)}\n\n"
        'Return JSON: {"items": [{"channel_id": "...", "tags": ["tag1"], "evidence": "brief reason"}]}'
    )


def _build_web_prompt(rows: list[dict[str, str]], tags: list[str], *, retry: bool = False) -> str:
    items = []
    for row in rows:
        items.append(
            {
                "channel_id": row.get("channel_id", ""),
                "channel_name": row.get("channel_name", ""),
                "handle": row.get("handle", ""),
            }
        )
    retry_note = "Your previous output was invalid. Follow the rules EXACTLY.\n\n" if retry else ""
    return (
        f"{retry_note}{WEB_RESEARCH_RULES}"
        "Search for each YouTube channel and find what topics they cover.\n"
        "Tag each channel using ONLY the allowed tags based on search evidence.\n\n"
        f"Allowed tags: {tags}\n\n"
        f"Channels (JSON): {json.dumps(items, ensure_ascii=True)}\n\n"
        'Return JSON: {"items": [{"channel_id": "...", "tags": ["tag1"], "evidence": "what you found", "evidence_url": "https://..."}]}'
    )


def _validate_tags(raw_tags: object, allowed: set[str], evidence: str | None) -> list[str] | None:
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


def main() -> int:
    configure_logging("teleclaude")
    logger = get_logger(__name__)
    try:
        # TextIOWrapper.reconfigure is available at runtime but not in TextIO stub
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(line_buffering=True)  # type: ignore[union-attr]
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Sync YouTube subscriptions into CSV and tag new rows.")
    parser.add_argument("--scope", choices=["person", "global"], default="person")
    parser.add_argument("--person", default="Morriz")
    parser.add_argument("--agents", default="claude", help=argparse.SUPPRESS)
    parser.add_argument(
        "--mode",
        choices=["normal", "web", "normal+web"],
        default="normal+web",
        help="Tagging mode: normal, web-only, or normal then web for n/a.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-evaluate already-tagged channels and add any new tags (never removes).",
    )
    parser.add_argument(
        "--fetch-subscriptions",
        action="store_true",
        help="Fetch subscriptions from YouTube (uses personal cookie). By default, uses existing CSV only.",
    )
    parser.add_argument("--thinking-mode", choices=["fast", "med", "slow"], default="fast")
    parser.add_argument(
        "--max-new",
        type=int,
        default=0,
        help="Limit new rows appended and tagged (0 = no limit)",
    )
    parser.add_argument(
        "--max-refresh",
        type=int,
        default=0,
        help="Limit channels to refresh (0 = no limit, only with --refresh)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=4,
        help="Max items per agent per batch (0 = no batching)",
    )
    parser.add_argument(
        "--prompt-batch",
        type=int,
        default=5,
        help="Channels per prompt (0 = single-row prompts)",
    )
    parser.add_argument(
        "--batch-pause-seconds",
        type=float,
        default=2.0,
        help="Pause between batches to avoid rate limits",
    )
    parser.add_argument("--dry-run", action="store_true", help="Do not write CSV changes")
    parser.add_argument("--verbose", action="store_true", help="Print per-row tagging results")
    parser.add_argument("--debug", action="store_true", help="Emit prompt + raw tagger output")
    # tools are configured per-agent; no CLI flag
    args = parser.parse_args()

    root = Path.home() / ".teleclaude"
    if args.scope == "global":
        cfg_path = root / "config" / "teleclaude.yml"
        csv_path = root / "subscriptions" / "youtube.csv"
    else:
        cfg_path = root / "people" / args.person / "teleclaude.yml"
        csv_path = root / "people" / args.person / "subscriptions" / "youtube.csv"

    tags = _load_tags(cfg_path)
    allowed_tags = set(tags)
    _ensure_csv(csv_path)
    if args.debug:
        print(
            json.dumps(
                {
                    "debug_cfg": {
                        "scope": args.scope,
                        "person": args.person,
                        "csv": str(csv_path),
                        "mode": args.mode,
                        "max_new": args.max_new,
                        "batch_size": args.batch_size,
                        "prompt_batch": args.prompt_batch,
                        "agents": args.agents,
                    }
                }
            )
        )

    existing = _read_csv(csv_path)
    if args.debug:
        print(json.dumps({"debug_existing": {"count": len(existing)}}))

    # Cleanup: remove tags that no longer exist in the allowed list
    stale_cleaned = _cleanup_stale_tags(existing, allowed_tags)
    if stale_cleaned > 0:
        if args.verbose:
            print(json.dumps({"stale_tags_cleaned": stale_cleaned}))
        if not args.dry_run:
            _write_csv(csv_path, existing)

    seen = {row.get("channel_id", "") for row in existing}

    new_rows: list[dict[str, str]] = []
    if args.fetch_subscriptions:
        channels = _call_youtube_helper()
        if args.debug:
            print(json.dumps({"debug_channels": {"count": len(channels)}}))
        for ch in channels:
            cid = ch.get("id", "")
            if not cid or cid in seen:
                continue
            new_rows.append(
                {
                    "channel_id": cid,
                    "channel_name": ch.get("title", ""),
                    "handle": ch.get("handle", "") or "",
                    "tags": "",
                    "_description": ch.get("description", "") or "",
                }
            )

    if args.max_new > 0:
        new_rows = new_rows[: args.max_new]
    if args.debug:
        print(json.dumps({"debug_new_rows": {"count": len(new_rows)}}))

    all_rows = existing + new_rows
    if new_rows and not args.dry_run:
        _write_csv(csv_path, all_rows)
        existing = _read_csv(csv_path)
        all_rows = existing
    pending = [row for row in new_rows if not row.get("tags", "").strip()] + [
        row for row in existing if not row.get("tags", "").strip()
    ]
    if args.max_new > 0:
        pending = pending[: args.max_new]
    if args.debug:
        print(json.dumps({"debug_pending": {"count": len(pending)}}))
    if not pending and not args.refresh:
        logger.info("tagging complete", updated=0)
        return 0

    # Agent order (comma-separated), fallback defaults
    if args.agents:
        agents = [a for a in args.agents.split(",") if a]
    else:
        agents = ["claude", "codex", "gemini"]
    rr = _round_robin(agents)

    tag_enum = sorted(set(tags + ["n/a"]))
    schema_single = {
        "type": "object",
        "properties": {"tags": {"type": "array", "items": {"type": "string", "enum": tag_enum}}},
        "required": ["tags"],
        "additionalProperties": False,
    }
    schema_batch = {
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
    }

    updates: dict[str, str] = {}
    per_agent = max(0, int(args.batch_size))
    batch_size = 0 if per_agent == 0 else per_agent * max(1, len(agents))

    def run_chunks(chunks: list[list[dict[str, str]]], use_web: bool, merge_mode: bool = False) -> None:
        """Process chunks. If merge_mode=True, add new tags to existing (never remove)."""
        nonlocal updates

        def retry_single(row: dict[str, str]) -> list[str]:
            agent = next(rr)
            retry_prompt = (
                _build_web_prompt([row], tags, retry=True) if use_web else _build_prompt(row, tags, retry=True)
            )
            result = _call_agent_cli(
                agent,
                args.thinking_mode,
                retry_prompt,
                schema_batch if use_web else schema_single,
                logger,
                debug=args.debug,
                tools="web_search" if use_web else "",
                mcp_tools="",
            )
            if result is None:
                return ["n/a"]
            if use_web:
                items = _safe_get_list(result, "items")
                by_id = {
                    _safe_get_str(i, "channel_id"): _safe_get_list(i, "tags") for i in items if isinstance(i, dict)
                }
                tagged = by_id.get(row.get("channel_id", ""), [])
            else:
                tagged = _safe_get_list(result, "tags")
            evidence = result.get("evidence")
            valid = _validate_tags(tagged, allowed_tags, evidence)
            return valid or ["n/a"]

        def process_group(group: list[dict[str, str]], agent: str) -> dict[str, str]:
            """Process a single group and return {channel_id: tags_str}."""
            group_results: dict[str, str] = {}
            prompt_batch = max(0, int(args.prompt_batch))

            if prompt_batch == 0 or len(group) == 1:
                row = group[0]
                if args.debug:
                    print(
                        json.dumps(
                            {
                                "debug_agent": agent,
                                "debug_row": {
                                    "channel_id": row.get("channel_id", ""),
                                    "channel_name": row.get("channel_name", ""),
                                },
                            }
                        )
                    )
                prompt = _build_web_prompt([row], tags) if use_web else _build_prompt(row, tags)
                start = time.monotonic()
                result = _call_agent_cli(
                    agent,
                    args.thinking_mode,
                    prompt,
                    schema_batch if use_web else schema_single,
                    logger,
                    debug=args.debug,
                    tools="web_search" if use_web else "",
                    mcp_tools="",
                )
                if args.debug:
                    print(json.dumps({"debug_duration_ms": int((time.monotonic() - start) * 1000)}))
                if result is None:
                    return group_results
                if use_web:
                    items = _safe_get_list(result, "items")
                    by_id = {_safe_get_str(i, "channel_id"): i for i in items if isinstance(i, dict)}
                    item = by_id.get(row.get("channel_id", ""), {})
                    tagged = _safe_get_list(item, "tags")
                    evidence = item.get("evidence")
                else:
                    tagged = _safe_get_list(result, "tags")
                    evidence = result.get("evidence")
                valid = _validate_tags(tagged, allowed_tags, evidence)
                if not valid:
                    valid = retry_single(row)
                group_results[row["channel_id"]] = ",".join(valid)
                if args.verbose:
                    print(
                        json.dumps(
                            {
                                "channel_id": row.get("channel_id", ""),
                                "channel_name": row.get("channel_name", ""),
                                "tags": valid,
                            }
                        )
                    )
            else:
                if args.debug:
                    print(
                        json.dumps(
                            {
                                "debug_agent": agent,
                                "debug_group": [
                                    {"channel_id": r.get("channel_id", ""), "channel_name": r.get("channel_name", "")}
                                    for r in group
                                ],
                            }
                        )
                    )
                prompt = _build_web_prompt(group, tags) if use_web else _build_batch_prompt(group, tags)
                start = time.monotonic()
                result = _call_agent_cli(
                    agent,
                    args.thinking_mode,
                    prompt,
                    schema_batch,
                    logger,
                    debug=args.debug,
                    tools="web_search" if use_web else "",
                    mcp_tools="",
                )
                if args.debug:
                    print(json.dumps({"debug_duration_ms": int((time.monotonic() - start) * 1000)}))
                if result is None:
                    return group_results
                items = _safe_get_list(result, "items")
                by_id = {_safe_get_str(i, "channel_id"): i for i in items if isinstance(i, dict)}
                for row in group:
                    cid = row.get("channel_id", "")
                    item = by_id.get(cid, {})
                    tagged = _safe_get_list(item, "tags")
                    evidence = item.get("evidence")
                    valid = _validate_tags(tagged, allowed_tags, evidence)
                    if not valid:
                        valid = retry_single(row)
                    group_results[cid] = ",".join(valid)
                    if args.verbose:
                        print(
                            json.dumps(
                                {
                                    "channel_id": row.get("channel_id", ""),
                                    "channel_name": row.get("channel_name", ""),
                                    "tags": valid,
                                }
                            )
                        )
            return group_results

        for idx, chunk in enumerate(chunks, start=1):
            if args.verbose:
                print(json.dumps({"batch_start": {"index": idx, "size": len(chunk)}}))
            # Enrich batch with full about-page descriptions before tagging
            _enrich_batch_descriptions(chunk)
            batch_updates: dict[str, str] = {}
            prompt_batch = max(0, int(args.prompt_batch))
            row_groups = (
                [chunk]
                if prompt_batch == 0
                else [chunk[i : i + prompt_batch] for i in range(0, len(chunk), prompt_batch)]
            )

            # Process all groups in parallel
            with ThreadPoolExecutor(max_workers=len(row_groups)) as executor:
                futures = {executor.submit(process_group, group, next(rr)): group for group in row_groups}
                for future in as_completed(futures):
                    group_results = future.result()
                    batch_updates.update(group_results)

            if batch_updates and not args.dry_run:
                for row in all_rows:
                    cid = row.get("channel_id", "")
                    if cid in batch_updates:
                        if merge_mode:
                            # Merge: add new tags, never remove existing
                            existing = set(
                                t.strip()
                                for t in (row.get("tags") or "").split(",")
                                if t.strip() and t.strip() != "n/a"
                            )
                            new_tags = set(
                                t.strip() for t in batch_updates[cid].split(",") if t.strip() and t.strip() != "n/a"
                            )
                            merged = sorted(existing | new_tags)
                            row["tags"] = ",".join(merged) if merged else "n/a"
                        else:
                            row["tags"] = batch_updates[cid]
                _write_csv(csv_path, all_rows)
            if batch_updates:
                for cid, tags_val in batch_updates.items():
                    updates[cid] = tags_val
            if args.verbose:
                print(json.dumps({"batch_end": {"index": idx, "size": len(chunk)}}))
            if args.batch_pause_seconds and idx < len(chunks):
                time.sleep(args.batch_pause_seconds)

    chunks = [pending] if batch_size == 0 else [pending[i : i + batch_size] for i in range(0, len(pending), batch_size)]
    if args.mode in {"normal", "normal+web"}:
        run_chunks(chunks, use_web=False)
    if args.mode in {"web", "normal+web"}:
        na_rows = [r for r in all_rows if (r.get("tags") or "").strip() == "n/a"]
        if args.max_new > 0:
            na_rows = na_rows[: args.max_new]
        if na_rows:
            web_chunks = (
                [na_rows]
                if batch_size == 0
                else [na_rows[i : i + batch_size] for i in range(0, len(na_rows), batch_size)]
            )
            run_chunks(web_chunks, use_web=True)

    # Refresh: re-evaluate already-tagged channels through the same normal → web flow
    # Results are merged (add new tags, never remove existing)
    if args.debug:
        print(json.dumps({"debug_refresh_flag": args.refresh}))
    if args.refresh:
        tagged_rows = [r for r in all_rows if (r.get("tags") or "").strip() and (r.get("tags") or "").strip() != "n/a"]
        if args.max_refresh > 0:
            tagged_rows = tagged_rows[: args.max_refresh]
        if tagged_rows:
            if args.verbose:
                print(json.dumps({"refresh_start": {"count": len(tagged_rows)}}))
            refresh_chunks = (
                [tagged_rows]
                if batch_size == 0
                else [tagged_rows[i : i + batch_size] for i in range(0, len(tagged_rows), batch_size)]
            )
            # Run both stages to find all possible new tags (merge mode)
            if args.mode in {"normal", "normal+web"}:
                run_chunks(refresh_chunks, use_web=False, merge_mode=True)
            if args.mode in {"web", "normal+web"}:
                run_chunks(refresh_chunks, use_web=True, merge_mode=True)
            if args.verbose:
                print(json.dumps({"refresh_end": {"count": len(tagged_rows)}}))

    if not updates:
        logger.info("tagging complete", updated=0)
        return 0

    logger.info("tagging complete", updated=len(updates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
