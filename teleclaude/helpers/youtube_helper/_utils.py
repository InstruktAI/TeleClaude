"""YouTube utility functions: safe JSON accessors, logging, backoff, and InnerTube headers."""

import hashlib
import http.cookiejar
import logging
import time
from datetime import UTC, datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from teleclaude.core.models import JsonDict, JsonValue
from teleclaude.helpers.youtube_helper._models import YouTubeBackoffError

__all__ = [
    "BACKOFF_FILE",
    "BACKOFF_SECONDS",
    "_INNERTUBE_API_URL",
    "_INNERTUBE_CONTEXT",
    "_build_innertube_headers",
    "_check_backoff",
    "_cookies_to_header",
    "_load_cookies_txt",
    "_refresh_cookies_if_needed",
    "_safe_get",
    "_safe_get_dict",
    "_safe_get_list",
    "_safe_get_str",
    "_trigger_backoff",
    "log",
]


def _safe_get(obj: JsonValue, *keys: str | int, default: JsonValue = None) -> JsonValue:
    """Safely traverse nested JSON structures with type safety.

    Args:
        obj: The starting JSON value (dict, list, or primitive)
        *keys: Keys (str for dicts) or indices (int for lists) to traverse
        default: Value to return if any key is missing or type is wrong

    Returns:
        The value at the nested path, or default if unreachable
    """
    current: JsonValue = obj
    for key in keys:
        if isinstance(key, int):
            if not isinstance(current, list) or key >= len(current):
                return default
            current = current[key]
        else:
            if not isinstance(current, dict):
                return default
            current = current.get(key, default)
            if current is default:
                return default
    return current


def _safe_get_dict(obj: JsonValue, *keys: str | int) -> JsonDict:
    """Safely get a nested dict, returning empty dict if not found or wrong type."""
    result = _safe_get(obj, *keys, default={})
    return result if isinstance(result, dict) else {}


def _safe_get_list(obj: JsonValue, *keys: str | int) -> list[JsonValue]:
    """Safely get a nested list, returning empty list if not found or wrong type."""
    result = _safe_get(obj, *keys, default=[])
    return result if isinstance(result, list) else []


def _safe_get_str(obj: JsonValue, *keys: str | int, default: str = "") -> str:
    """Safely get a nested string, returning default if not found or wrong type."""
    result = _safe_get(obj, *keys, default=default)
    return result if isinstance(result, str) else default


# Configure logging to youtube_helper.log
log_dir = Path.home() / ".claude" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "youtube_helper.log"

log = logging.getLogger("youtube_helper")
log.setLevel(logging.INFO)
if not any(isinstance(handler, RotatingFileHandler) for handler in log.handlers):
    handler = RotatingFileHandler(
        str(log_file),
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [youtube_helper] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    log.addHandler(handler)


# ---------------------------------------------------------------------------
# Circuit breaker for authenticated YouTube requests
# ---------------------------------------------------------------------------

BACKOFF_FILE = Path.home() / ".config" / "youtube" / ".backoff"
BACKOFF_SECONDS = 600  # 10 minutes


def _check_backoff() -> None:
    """Raise if we're still in a backoff window."""
    if not BACKOFF_FILE.exists():
        return
    try:
        expires = datetime.fromisoformat(BACKOFF_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        BACKOFF_FILE.unlink(missing_ok=True)
        return
    if datetime.now(UTC) < expires:
        remaining = int((expires - datetime.now(UTC)).total_seconds())
        raise YouTubeBackoffError(
            f"YouTube backoff active — retrying in {remaining}s. "
            f"Previous request triggered a protective response from YouTube."
        )
    BACKOFF_FILE.unlink(missing_ok=True)


def _trigger_backoff(reason: str) -> None:
    """Activate the circuit breaker."""
    expires = datetime.now(UTC) + timedelta(seconds=BACKOFF_SECONDS)
    BACKOFF_FILE.parent.mkdir(parents=True, exist_ok=True)
    BACKOFF_FILE.write_text(expires.isoformat(), encoding="utf-8")
    log.warning("YouTube backoff triggered for %ds: %s", BACKOFF_SECONDS, reason)


# ---------------------------------------------------------------------------
# Watch history via InnerTube browse API (aiohttp — no yt-dlp needed)
# ---------------------------------------------------------------------------

_INNERTUBE_API_URL = "https://www.youtube.com/youtubei/v1/browse"
_INNERTUBE_CONTEXT = {
    "client": {
        "clientName": "WEB",
        "clientVersion": "2.20240101.00.00",
        "hl": "en",
        "gl": "US",
    }
}


def _load_cookies_txt(path: str) -> dict[str, str]:
    """Load a Netscape cookies.txt file and return youtube.com cookies as a dict."""
    jar = http.cookiejar.MozillaCookieJar(path)
    jar.load(ignore_discard=True, ignore_expires=True)
    return {c.name: c.value for c in jar if c.domain and ".youtube.com" in c.domain and c.value is not None}


def _cookies_to_header(cookies: dict[str, str]) -> str:
    """Format cookie dict as a Cookie header string."""
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def _build_innertube_headers(cookies_file: str | None) -> tuple[dict[str, str], str]:
    """Build InnerTube headers and resolve cookies file path."""
    default_cookies = Path.home() / ".config" / "youtube" / "cookies.txt"
    if not cookies_file and default_cookies.exists():
        cookies_file = str(default_cookies)
    if not cookies_file:
        raise FileNotFoundError(
            "No cookies file found. Export YouTube cookies to "
            "~/.config/youtube/cookies.txt (Netscape format) using a browser extension."
        )

    cookies = _load_cookies_txt(cookies_file)
    if not cookies:
        raise ValueError(f"No youtube.com cookies found in {cookies_file}")

    cookie_header = _cookies_to_header(cookies)
    sapid = cookies.get("SAPISID") or cookies.get("__Secure-3PAPISID") or ""
    headers: dict[str, str] = {
        "Cookie": cookie_header,
        "Content-Type": "application/json",
        "Origin": "https://www.youtube.com",
        "X-Youtube-Client-Name": "1",
        "X-Youtube-Client-Version": "2.20240101.00.00",
    }
    if sapid:
        ts = str(int(time.time()))
        hash_input = f"{ts} {sapid} https://www.youtube.com"
        sapid_hash = hashlib.sha1(hash_input.encode()).hexdigest()
        headers["Authorization"] = f"SAPISIDHASH {ts}_{sapid_hash}"

    return headers, cookies_file


_COOKIE_REFRESH_LOCK = Path.home() / ".config" / "youtube" / ".refresh_lock"
_COOKIE_REFRESH_COOLDOWN_SECONDS = 10 * 60


def _refresh_cookies_if_needed() -> bool:
    """Run the cookie refresh script if profile exists. Returns True if successful."""
    profile_dir = Path.home() / ".config" / "youtube" / "playwright-profile"
    if not profile_dir.exists():
        log.warning("Playwright profile not found at %s - cannot auto-refresh cookies", profile_dir)
        return False

    if _COOKIE_REFRESH_LOCK.exists():
        age = time.time() - _COOKIE_REFRESH_LOCK.stat().st_mtime
        if age < _COOKIE_REFRESH_COOLDOWN_SECONDS:
            log.warning("Cookie refresh cooldown active (%.0fs remaining)", _COOKIE_REFRESH_COOLDOWN_SECONDS - age)
            return False

    try:
        from teleclaude.helpers.youtube.refresh_cookies import refresh_cookies
    except Exception as exc:
        log.warning("refresh_cookies import failed - cannot auto-refresh cookies: %s", exc)
        return False

    log.info("Auto-refreshing YouTube cookies...")
    try:
        _COOKIE_REFRESH_LOCK.parent.mkdir(parents=True, exist_ok=True)
        _COOKIE_REFRESH_LOCK.touch()
        return refresh_cookies(
            profile_dir=Path.home() / ".config" / "youtube" / "playwright-profile",
            output_path=Path.home() / ".config" / "youtube" / "cookies.txt",
            headless=True,
        )
    except Exception as e:
        log.error("Cookie refresh error: %s", e)
        return False
