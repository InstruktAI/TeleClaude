#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "playwright",
# ]
# ///
"""Refresh YouTube cookies using Playwright with dedicated automation profile."""

import argparse
import importlib
import sys
import time
from pathlib import Path
from typing import Any

from teleclaude.core.models import JsonDict

# Persistent profile for automation (separate from system Chrome)
DEFAULT_PROFILE = Path.home() / ".config" / "youtube" / "playwright-profile"
DEFAULT_OUTPUT = Path.home() / ".config" / "youtube" / "cookies.txt"


def cookies_to_netscape(cookies: list[JsonDict]) -> str:
    """Convert Playwright cookies to Netscape cookies.txt format."""
    lines = [
        "# Netscape HTTP Cookie File",
        "# https://curl.haxx.se/docs/http-cookies.html",
        f"# Refreshed by refresh_cookies.py at {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    for c in cookies:
        domain = c.get("domain", "")
        if not isinstance(domain, str):
            continue
        if ".youtube.com" not in domain and ".google.com" not in domain:
            continue

        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        path_val = c.get("path", "/")
        path = path_val if isinstance(path_val, str) else "/"
        secure = "TRUE" if c.get("secure", False) else "FALSE"
        expires_val = c.get("expires", time.time() + 86400 * 365)
        expiry = int(expires_val) if isinstance(expires_val, int | float) else int(time.time() + 86400 * 365)
        name_val = c.get("name", "")
        name = name_val if isinstance(name_val, str) else ""
        value_val = c.get("value", "")
        value = value_val if isinstance(value_val, str) else ""

        lines.append(f"{domain}\t{include_subdomains}\t{path}\t{secure}\t{expiry}\t{name}\t{value}")

    return "\n".join(lines)


def setup_profile(profile_dir: Path) -> bool:  # pylint: disable=too-many-statements  # Sequential pipeline is intentionally flat.
    """Interactive setup: launch browser for user to log in to YouTube.

    Args:
        profile_dir: Where to store the persistent profile

    Returns:
        True if setup completed successfully
    """
    sync_api = importlib.import_module("playwright.sync_api")
    sync_playwright = sync_api.sync_playwright

    profile_dir.mkdir(parents=True, exist_ok=True)
    print(f"Profile directory: {profile_dir}")
    print()
    print("=" * 60)
    print("SETUP MODE")
    print("=" * 60)
    print()
    print("A browser window will open. Please:")
    print("1. Log in to your YouTube/Google account")
    print("2. Make sure you can see your watch history")
    print("3. Close the browser window when done")
    print()

    with sync_playwright() as p:
        # Use Chrome channel for better compatibility with Google login
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=False,
            channel="chrome",  # Use real Chrome instead of Playwright's Chromium
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-infobars",
                "--disable-extensions",
            ],
            ignore_default_args=["--enable-automation"],
        )

        page = context.new_page()

        # Navigate to YouTube directly (less suspicious than accounts.google.com)
        page.goto("https://www.youtube.com")

        print()
        print("Browser opened. Log in to Google/YouTube.")
        print("After logging in, navigate to youtube.com/feed/history to verify access.")
        print("Then close the browser window when done.")
        print()

        # Store cookies captured before close
        cookies = []

        def capture_cookies():  # type: ignore[no-untyped-def]
            nonlocal cookies
            try:
                cookies = context.cookies()
                cookie_names = {c["name"] for c in cookies}
                essential = {"SID", "HSID", "SSID", "APISID", "SAPISID"}
                found = essential & cookie_names
                if found:
                    print(f"Captured {len(cookies)} cookies - AUTH DETECTED: {found}")
                else:
                    print(f"Captured {len(cookies)} cookies (no auth yet): {list(cookie_names)[:5]}...")
            except Exception:  # pylint: disable=broad-exception-caught
                pass

        # Capture cookies periodically and on close
        context.on("close", lambda: None)  # Keep context alive

        try:
            while len(context.pages) > 0:
                capture_cookies()  # type: ignore[no-untyped-call]
                time.sleep(2)
        except Exception:  # pylint: disable=broad-exception-caught
            pass

        # Final capture attempt
        capture_cookies()  # type: ignore[no-untyped-call]

    cookie_names = {c["name"] for c in cookies}
    essential = {"SID", "HSID", "SSID", "APISID", "SAPISID"}
    missing = essential - cookie_names

    if missing:
        print(f"\nSetup incomplete - missing auth cookies: {missing}")
        print("Please run --setup again and make sure to fully log in.")
        return False

    print(f"\nSetup complete! Found {len(cookies)} cookies.")
    print("You can now run without --setup to refresh cookies.")
    return True


def refresh_cookies(
    profile_dir: Path,
    output_path: Path,
    headless: bool = True,
    timeout: int = 30000,
) -> bool:
    """Refresh YouTube cookies using the dedicated Playwright profile.

    Args:
        profile_dir: Path to Playwright profile (created via --setup)
        output_path: Where to save cookies.txt
        headless: Run headless (safe since we control this profile)
        timeout: Page load timeout in ms

    Returns:
        True if successful
    """
    sync_api = importlib.import_module("playwright.sync_api")
    sync_playwright = sync_api.sync_playwright

    if not profile_dir.exists():
        print(f"Error: Profile not found at {profile_dir}", file=sys.stderr)
        print("Run with --setup first to create the profile.", file=sys.stderr)
        return False

    print(f"Using profile: {profile_dir}")

    with sync_playwright() as p:
        cookies = _extract_playwright_cookies(
            playwright=p,
            profile_dir=profile_dir,
            headless=headless,
            timeout=timeout,
        )

    yt_cookies = _filter_youtube_cookies(cookies)
    print(f"Filtered to {len(yt_cookies)} YouTube/Google cookies")

    missing = _missing_auth_cookies(yt_cookies)
    if missing:
        print(f"Warning: Missing essential cookies: {missing}", file=sys.stderr)
        print("Session may have expired. Run --setup again to re-login.", file=sys.stderr)
        return False

    netscape = cookies_to_netscape(yt_cookies)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(netscape, encoding="utf-8")
    print(f"Saved {len(yt_cookies)} cookies to {output_path}")

    return True


def _extract_playwright_cookies(*, playwright: Any, profile_dir: Path, headless: bool, timeout: int) -> list[JsonDict]:
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=headless,
        channel="chrome",
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
        ],
        ignore_default_args=["--enable-automation"],
    )
    try:
        page = context.new_page()
        print("Navigating to youtube.com...")
        try:
            page.goto("https://www.youtube.com", timeout=timeout, wait_until="networkidle")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"Navigation warning (may still work): {exc}", file=sys.stderr)
        page.wait_for_timeout(2000)
        raw_cookies = context.cookies(["https://www.youtube.com", "https://accounts.google.com"])
        cookies = [cookie for cookie in raw_cookies if isinstance(cookie, dict)]
        print(f"Extracted {len(cookies)} cookies")
        return cookies
    finally:
        context.close()


def _filter_youtube_cookies(cookies: list[JsonDict]) -> list[JsonDict]:
    filtered: list[JsonDict] = []
    for cookie in cookies:
        domain_value = cookie.get("domain", "")
        domain = domain_value if isinstance(domain_value, str) else ""
        if ".youtube.com" in domain or ".google.com" in domain:
            filtered.append(cookie)
    return filtered


def _missing_auth_cookies(cookies: list[JsonDict]) -> set[str]:
    cookie_names = {name_value for cookie in cookies if isinstance((name_value := cookie.get("name")), str)}
    essential = {"SID", "HSID", "SSID", "APISID", "SAPISID"}
    return essential - cookie_names


def main():  # type: ignore[no-untyped-def]
    """CLI entrypoint for refreshing YouTube cookies via Playwright."""
    parser = argparse.ArgumentParser(
        description="Refresh YouTube cookies via Playwright",
        epilog="First run with --setup to log in, then run without flags to refresh.",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Interactive setup: open browser to log in to YouTube",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        default=DEFAULT_PROFILE,
        help=f"Playwright profile directory (default: {DEFAULT_PROFILE})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output cookies.txt path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--no-headless",
        action="store_true",
        help="Show browser window during refresh (default: headless)",
    )
    args = parser.parse_args()

    if args.setup:
        success = setup_profile(args.profile)
    else:
        success = refresh_cookies(
            profile_dir=args.profile,
            output_path=args.output,
            headless=not args.no_headless,
        )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()  # type: ignore[no-untyped-call]
