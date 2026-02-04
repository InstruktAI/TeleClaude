#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Send an ops Telegram message via Bot API.

This entrypoint is intended for break-glass alerts when TeleClaude is down.
It targets a username (not chat IDs) via TELEGRAM_ALERT_USERNAME by default.
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.parse
import urllib.request
from typing import TypedDict

from instrukt_ai_logging import configure_logging, get_logger

from teleclaude.constants import MAIN_MODULE

configure_logging("teleclaude")
logger = get_logger(__name__)


DEFAULT_TOKEN_ENV = "TELEGRAM_BOT_TOKEN"
DEFAULT_USERNAME_ENV = "TELEGRAM_ALERT_USERNAME"
DEFAULT_CHAT_ID_ENV = "TELEGRAM_SUPERGROUP_ID"


class ApiResponse(TypedDict, total=False):
    ok: bool
    description: str
    result: object


def _post_form(url: str, data: dict[str, str], timeout_s: float) -> ApiResponse:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=encoded, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
        body = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"ok": False, "description": f"Non-JSON response: {body[:2000]}"}


def _normalize_username(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    return value if value.startswith("@") else f"@{value}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send an ops Telegram message (Bot API sendMessage).")
    parser.add_argument("--token-env", default=DEFAULT_TOKEN_ENV, help="Env var containing bot token.")
    parser.add_argument(
        "--username-env",
        default=DEFAULT_USERNAME_ENV,
        help="Env var containing the target Telegram username (without chat IDs).",
    )
    parser.add_argument(
        "--chat-id-env",
        default=DEFAULT_CHAT_ID_ENV,
        help="Env var containing the target Telegram chat_id (e.g. supergroup).",
    )
    parser.add_argument(
        "--to",
        default=None,
        help="Override target username (e.g., @Moreaze).",
    )
    parser.add_argument(
        "--chat-id",
        default=None,
        help="Override target chat_id (preferred for groups).",
    )
    parser.add_argument("--text", required=True, help="Message text.")
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP timeout seconds.")
    parser.add_argument("--parse-mode", default=None, help="Optional parse_mode (e.g. MarkdownV2, HTML).")

    args = parser.parse_args(argv)

    token = os.getenv(args.token_env)
    if not token:
        logger.error("missing_token_env", env=args.token_env)
        return 2

    raw_chat_id = args.chat_id or os.getenv(args.chat_id_env, "")
    chat_id = str(raw_chat_id).strip() if raw_chat_id is not None else ""

    raw_username = args.to or os.getenv(args.username_env, "")
    username = _normalize_username(raw_username)

    if not chat_id and not username:
        logger.error("missing_alert_target", chat_id_env=args.chat_id_env, username_env=args.username_env)
        return 2

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict[str, str] = {
        "chat_id": chat_id or username,
        "text": str(args.text),
        "disable_web_page_preview": "true",
    }
    if args.parse_mode:
        payload["parse_mode"] = str(args.parse_mode)

    result = _post_form(url, payload, timeout_s=float(args.timeout))
    if not result.get("ok"):
        desc = str(result.get("description") or result)
        logger.error("telegram_send_failed", description=desc)
        return 1

    logger.info("telegram_send_ok", to=chat_id or username)
    return 0


if __name__ == MAIN_MODULE:
    raise SystemExit(main())
