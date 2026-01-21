#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Notify the "Agents" topic (out-of-band) for smoke tests.

This script is meant to be called from cron/launchd. It sends via Telegram Bot API
so it still works when TeleClaude is down.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import TypedDict

from instrukt_ai_logging import configure_logging, get_logger

from teleclaude.constants import MAIN_MODULE
from teleclaude.paths import REPO_ROOT

configure_logging("teleclaude")
logger = get_logger(__name__)


@dataclass
class AlertState:
    backoff_s: int = 60
    next_allowed_at: float = 0.0


@dataclass
class DestinationState:
    """Persisted destination info (e.g., created topic/thread id)."""

    thread_id: str | None = None


STATE_DIR = REPO_ROOT / "logs" / "monitoring"
STATE_PATH = STATE_DIR / "agents_alert_state.json"
DEST_PATH = STATE_DIR / "agents_alert_destination.json"


def _ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


def _load_state() -> AlertState:
    if not STATE_PATH.exists():
        return AlertState()
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return AlertState(
            backoff_s=int(data.get("backoff_s", 60)),
            next_allowed_at=float(data.get("next_allowed_at", 0.0)),
        )
    except Exception:
        return AlertState()


def _save_state(state: AlertState) -> None:
    _ensure_state_dir()
    STATE_PATH.write_text(
        json.dumps(
            {"backoff_s": int(state.backoff_s), "next_allowed_at": float(state.next_allowed_at)},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _reset_state() -> None:
    try:
        STATE_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def _load_destination() -> DestinationState:
    if not DEST_PATH.exists():
        return DestinationState()
    try:
        data = json.loads(DEST_PATH.read_text(encoding="utf-8"))
        thread_id = data.get("thread_id")
        return DestinationState(thread_id=str(thread_id) if thread_id else None)
    except Exception:
        return DestinationState()


def _save_destination(dest: DestinationState) -> None:
    _ensure_state_dir()
    DEST_PATH.write_text(
        json.dumps({"thread_id": dest.thread_id}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class ApiResponse(TypedDict, total=False):
    ok: bool
    description: str
    result: object


def _telegram_api_post(method: str, payload: dict[str, str], timeout_s: float = 10.0) -> ApiResponse:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        return {"ok": False, "description": "Missing TELEGRAM_BOT_TOKEN"}

    url = f"https://api.telegram.org/bot{token}/{method}"
    encoded = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=encoded, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310
        body = resp.read().decode("utf-8", errors="replace")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"ok": False, "description": f"Non-JSON response: {body[:2000]}"}


def _ensure_agents_thread_id(chat_id: str) -> str | None:
    """Ensure we have a topic/thread id for the Agents channel."""
    dest = _load_destination()
    if dest.thread_id:
        return dest.thread_id

    result = _telegram_api_post(
        "createForumTopic",
        {"chat_id": str(chat_id), "name": "Agents"},
        timeout_s=10.0,
    )
    if not result.get("ok"):
        return None

    created = result.get("result")
    if not isinstance(created, dict):
        return None

    thread_id = created.get("message_thread_id")
    if not thread_id:
        return None

    dest.thread_id = str(thread_id)
    _save_destination(dest)
    return dest.thread_id


def _should_throttle(state: AlertState) -> bool:
    return time.time() < state.next_allowed_at


def _bump_backoff(state: AlertState) -> AlertState:
    next_backoff = min(state.backoff_s * 2, 3600)
    next_allowed_at = time.time() + next_backoff
    return AlertState(backoff_s=next_backoff, next_allowed_at=next_allowed_at)


def _format_message(prefix_host: str | None, text: str) -> str:
    if prefix_host:
        return f"[{prefix_host}] {text}"
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Notify Agents topic with backoff.")
    parser.add_argument("--reset", action="store_true", help="Reset backoff state.")
    parser.add_argument("--prefix-host", default=None, help="Prefix message with host name.")
    parser.add_argument("--text", default="Smoke test failed", help="Message text.")
    args = parser.parse_args(argv)

    if args.reset:
        _reset_state()
        logger.info("notify_reset")
        return 0

    chat_id = os.getenv("TELEGRAM_SUPERGROUP_ID")
    if not chat_id:
        logger.error("missing_supergroup_id")
        return 2

    state = _load_state()
    if _should_throttle(state):
        logger.info("notify_throttled", next_allowed_at=state.next_allowed_at)
        return 0

    thread_id = _ensure_agents_thread_id(chat_id)
    message = _format_message(args.prefix_host, args.text)

    payload = {
        "chat_id": str(chat_id),
        "text": message,
        "disable_web_page_preview": "true",
    }
    if thread_id:
        payload["message_thread_id"] = str(thread_id)

    result = _telegram_api_post("sendMessage", payload, timeout_s=10.0)
    ok = bool(result.get("ok"))

    if ok:
        _save_state(AlertState(backoff_s=60, next_allowed_at=0.0))
        logger.info("notify_sent")
        return 0

    state = _bump_backoff(state)
    _save_state(state)
    logger.error("notify_failed", backoff_s=state.backoff_s)
    return 1


if __name__ == MAIN_MODULE:
    raise SystemExit(main())
