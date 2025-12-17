#!/usr/bin/env python3
"""Notify the "Agents" topic (out-of-band) for smoke tests.

This script is meant to be called from cron/launchd. It sends via Telegram Bot API
directly, so it still works when TeleClaude is down.

Identity: reuses the existing TeleClaude bot identity (`TELEGRAM_BOT_TOKEN`).

Destination:
- `TELEGRAM_SUPERGROUP_ID` (required) as chat_id
- Automatically creates (or reuses) a Telegram topic named "Agents" when possible.

Rate limiting:
- Exponential backoff on repeated calls, capped to once per hour.
- Use `--reset` after a successful smoke run to clear backoff state.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AlertState:
    backoff_s: int = 60
    next_allowed_at: float = 0.0


@dataclass
class DestinationState:
    """Persisted destination info (e.g., created topic/thread id)."""

    thread_id: str | None = None


def _project_root() -> Path:
    # bin/notify_agents.py -> project root
    return Path(__file__).resolve().parent.parent


def _state_dir() -> Path:
    # Keep state in-repo so it's discoverable in IDE searches, but ignored by git.
    # (logs/ is already gitignored in this repo.)
    logs_dir = _project_root() / "logs"
    logs_dir.mkdir(exist_ok=True)
    state_dir = logs_dir / "monitoring"
    state_dir.mkdir(exist_ok=True)
    return state_dir


def _state_path() -> Path:
    return _state_dir() / "agents_alert_state.json"


def _load_state() -> AlertState:
    path = _state_path()
    if not path.exists():
        return AlertState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return AlertState(
            backoff_s=int(data.get("backoff_s", 60)),
            next_allowed_at=float(data.get("next_allowed_at", 0.0)),
        )
    except Exception:
        return AlertState()


def _save_state(state: AlertState) -> None:
    path = _state_path()
    path.write_text(
        json.dumps(
            {"backoff_s": int(state.backoff_s), "next_allowed_at": float(state.next_allowed_at)},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _reset_state() -> None:
    path = _state_path()
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def _dest_path() -> Path:
    return _state_dir() / "agents_alert_destination.json"


def _load_destination() -> DestinationState:
    path = _dest_path()
    if not path.exists():
        return DestinationState()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        thread_id = data.get("thread_id")
        return DestinationState(thread_id=str(thread_id) if thread_id else None)
    except Exception:
        return DestinationState()


def _save_destination(dest: DestinationState) -> None:
    path = _dest_path()
    path.write_text(
        json.dumps({"thread_id": dest.thread_id}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _telegram_api_post(method: str, payload: dict[str, str], timeout_s: float = 10.0) -> dict:
    import urllib.parse
    import urllib.request

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
    """Ensure we have a topic/thread id for the Agents channel.

    Best-effort:
    - Reuse cached thread id if present.
    - Attempt to create a forum topic named "Agents" in the configured supergroup.
      If the chat isn't a forum or bot lacks rights, return None (fallback to main chat).
    """
    dest = _load_destination()
    if dest.thread_id:
        return dest.thread_id

    result = _telegram_api_post(
        "createForumTopic",
        {"chat_id": str(chat_id), "name": "Agents"},
        timeout_s=10.0,
    )
    if not isinstance(result, dict) or not result.get("ok"):
        return None

    created = result.get("result") if isinstance(result, dict) else None
    if not isinstance(created, dict):
        return None

    thread_id = created.get("message_thread_id")
    if not thread_id:
        return None

    dest.thread_id = str(thread_id)
    _save_destination(dest)
    return dest.thread_id


def _run_send_telegram(chat_id: str, thread_id: str | None, text: str) -> int:
    script_dir = Path(__file__).resolve().parent
    send_script = script_dir / "send_telegram.py"
    if not send_script.exists():
        print(f"ERROR: missing {send_script}", file=sys.stderr)
        return 2

    args = [
        sys.executable,
        str(send_script),
        "--chat-id",
        str(chat_id),
        "--text",
        str(text),
    ]
    if thread_id:
        args += ["--thread-id", str(thread_id)]

    import subprocess

    result = subprocess.run(args, check=False)  # noqa: S603
    return int(result.returncode)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Notify Agents topic with exponential backoff (max 1/hour).")
    parser.add_argument("text", nargs="?", help="Message text to send.")
    parser.add_argument("--reset", action="store_true", help="Reset backoff state (call on success).")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass backoff (still uses normal env vars); use sparingly.",
    )
    parser.add_argument(
        "--prefix-host",
        action="store_true",
        help="Prefix message with hostname/computer name if available.",
    )

    args = parser.parse_args(argv)

    if args.reset:
        _reset_state()
        return 0

    if not args.text:
        print("ERROR: missing text (or pass --reset)", file=sys.stderr)
        return 2

    chat_id = os.getenv("TELEGRAM_SUPERGROUP_ID")
    if not chat_id:
        print("ERROR: missing TELEGRAM_SUPERGROUP_ID", file=sys.stderr)
        return 2

    thread_id = _ensure_agents_thread_id(chat_id)

    state = _load_state()
    now = time.time()
    if not args.force and now < state.next_allowed_at:
        # Silent no-op: smoke tests shouldn't spam; they should still fail independently.
        return 0

    text = str(args.text)
    if args.prefix_host:
        host = os.getenv("COMPUTER_NAME") or os.getenv("HOSTNAME") or os.uname().nodename
        text = f"[{host}] {text}"

    rc = _run_send_telegram(chat_id=chat_id, thread_id=thread_id, text=text)
    if rc != 0:
        # Don't advance backoff on delivery failure; caller should see the failure.
        return rc

    # Successful send: exponential backoff, capped to 1 hour.
    state.next_allowed_at = now + float(state.backoff_s)
    state.backoff_s = min(max(60, state.backoff_s * 2), 3600)
    _save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
