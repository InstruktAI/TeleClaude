#!/usr/bin/env python3
"""Send a Telegram message via Bot API.

Designed for cron/launchd smoke tests: this script must work even when TeleClaude is down.

Token/identity:
- Defaults to `TELEGRAM_BOT_TOKEN` (same env var TeleClaude uses).
- Override with `--token-env`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path


def _post_form(url: str, data: dict[str, str], timeout_s: float) -> dict:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=encoded, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
        body = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"ok": False, "description": f"Non-JSON response: {body[:2000]}"}


def _looks_like_int(value: str) -> bool:
    value = value.strip()
    if value.startswith(("+", "-")):
        value = value[1:]
    return value.isdigit()


def _resolve_chat_id_via_telethon(target: str) -> str | None:
    """Resolve a human-friendly target into a numeric chat_id using a Telegram user session.

    Supports:
    - @username
    - display name (best-effort match against dialog titles)

    Requires an existing telegram_search setup:
    - ~/.config/telegram_search/config.json
    - ~/.config/telegram_search/session.txt
    """
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except Exception:
        return None

    config_path = Path.home() / ".config" / "telegram_search" / "config.json"
    session_path = Path.home() / ".config" / "telegram_search" / "session.txt"
    if not config_path.exists() or not session_path.exists():
        return None

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        session = session_path.read_text(encoding="utf-8").strip()
        api_id = config["api_id"]
        api_hash = config["api_hash"]
    except Exception:
        return None

    async def _run() -> str | None:
        client = TelegramClient(StringSession(session), api_id, api_hash)
        await client.connect()
        try:
            query = target.strip()
            # Prefer direct username resolution.
            if query.startswith("@"):
                entity = await client.get_entity(query)
                return str(getattr(entity, "id", None)) if getattr(entity, "id", None) else None

            dialogs = await client.get_dialogs(limit=200)
            needle = query.casefold()

            def _score(name: str) -> tuple[int, int]:
                hay = name.casefold()
                if hay == needle:
                    return (0, len(hay))
                if hay.startswith(needle):
                    return (1, len(hay))
                if needle in hay:
                    return (2, len(hay))
                return (9, len(hay))

            best: tuple[tuple[int, int], object] | None = None
            for dialog in dialogs:
                name = getattr(dialog, "name", "") or ""
                if not name:
                    continue
                score = _score(name)
                if score[0] == 9:
                    continue
                if best is None or score < best[0]:
                    best = (score, dialog.entity)

            if not best:
                return None

            entity = best[1]
            entity_id = getattr(entity, "id", None)
            return str(entity_id) if entity_id else None
        finally:
            await client.disconnect()

    try:
        import asyncio

        return asyncio.run(_run())
    except Exception:
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send a Telegram bot message (Bot API sendMessage).")
    parser.add_argument("--token-env", default="TELEGRAM_BOT_TOKEN", help="Env var containing bot token.")
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--chat-id", help="Target chat_id (numeric ID or @channelusername).")
    target_group.add_argument(
        "--to",
        help="Target recipient: numeric chat_id, @username, or display name (resolved via local Telegram session).",
    )
    parser.add_argument(
        "--thread-id",
        default=None,
        help="Optional message_thread_id (topic id) for supergroup topics.",
    )
    parser.add_argument("--text", required=True, help="Message text.")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout seconds.")
    parser.add_argument("--parse-mode", default=None, help="Optional parse_mode (e.g. MarkdownV2, HTML).")

    args = parser.parse_args(argv)

    token = os.getenv(args.token_env)
    if not token:
        print(f"ERROR: missing {args.token_env}", file=sys.stderr)
        return 2

    # Determine chat_id
    chat_id: str | None
    if args.chat_id:
        chat_id = str(args.chat_id).strip()
    else:
        raw = str(args.to).strip()
        if _looks_like_int(raw) or raw.startswith("@"):
            chat_id = raw
        else:
            chat_id = _resolve_chat_id_via_telethon(raw)

    if not chat_id:
        print("ERROR: could not resolve recipient (use --chat-id or a resolvable --to value)", file=sys.stderr)
        return 2

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, str] = {
        "chat_id": chat_id,
        "text": str(args.text),
        "disable_web_page_preview": "true",
    }
    if args.thread_id:
        payload["message_thread_id"] = str(args.thread_id)
    if args.parse_mode:
        payload["parse_mode"] = str(args.parse_mode)

    result = _post_form(url, payload, timeout_s=float(args.timeout))
    if not isinstance(result, dict) or not result.get("ok"):
        desc = ""
        if isinstance(result, dict):
            desc = str(result.get("description") or result)
        print(f"ERROR: telegram sendMessage failed: {desc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
