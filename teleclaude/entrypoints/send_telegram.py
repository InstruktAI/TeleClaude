#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Send an ops Telegram message via Bot API.

This entrypoint is intended for break-glass alerts when TeleClaude is down.
It uses the configured Telegram alert username or chat ID by default.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from typing import TypedDict

from instrukt_ai_logging import configure_logging, get_logger

from teleclaude.config import config
from teleclaude.constants import MAIN_MODULE

configure_logging("teleclaude")
logger = get_logger(__name__)


TOKEN_ENV_FLAG = "--token-env"
USERNAME_ENV_FLAG = "--username-env"
CHAT_ID_ENV_FLAG = "--chat-id-env"
TOKEN_CONFIG_PATH = "telegram.bot_token"
USERNAME_CONFIG_PATH = "telegram.alert_username"
CHAT_ID_CONFIG_PATH = "telegram.alert_chat_id"
DEPRECATED_FLAGS = {
    TOKEN_ENV_FLAG: TOKEN_CONFIG_PATH,
    USERNAME_ENV_FLAG: USERNAME_CONFIG_PATH,
    CHAT_ID_ENV_FLAG: CHAT_ID_CONFIG_PATH,
}


class ApiResponse(TypedDict, total=False):
    """Subset of Telegram Bot API response fields used by this entrypoint."""

    ok: bool
    description: str
    result: object


def _post_form(url: str, data: dict[str, str], timeout_s: float) -> ApiResponse:
    encoded = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=encoded, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(body)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return {"ok": False, "description": f"Non-JSON response: {body[:2000]}"}


def _normalize_username(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    return value if value.startswith("@") else f"@{value}"


def main(argv: list[str] | None = None) -> int:
    """Parse CLI options and send a Telegram Bot API message."""
    parser = argparse.ArgumentParser(description="Send an ops Telegram message (Bot API sendMessage).")
    parser.add_argument(TOKEN_ENV_FLAG, help="Deprecated; configure telegram.bot_token instead.")
    parser.add_argument(
        USERNAME_ENV_FLAG,
        help="Deprecated; configure telegram.alert_username instead.",
    )
    parser.add_argument(
        CHAT_ID_ENV_FLAG,
        help="Deprecated; configure telegram.alert_chat_id instead.",
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

    command_args = argv if argv is not None else sys.argv[1:]
    args = parser.parse_args(command_args)
    for flag, config_path in DEPRECATED_FLAGS.items():
        if any(argument == flag or argument.startswith(f"{flag}=") for argument in command_args):
            logger.warning("deprecated_argument", argument=flag, config_path=config_path)

    token = config.telegram.bot_token
    if not token:
        logger.error("missing_config", config_path=TOKEN_CONFIG_PATH)
        return 2

    raw_chat_id = args.chat_id or config.telegram.alert_chat_id or ""
    chat_id = str(raw_chat_id).strip() if raw_chat_id is not None else ""

    raw_username = args.to or config.telegram.alert_username or ""
    username = _normalize_username(raw_username)

    if not chat_id and not username:
        logger.error("missing_alert_target", chat_id_config=CHAT_ID_CONFIG_PATH, username_config=USERNAME_CONFIG_PATH)
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
