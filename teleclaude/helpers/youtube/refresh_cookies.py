#!/usr/bin/env -S uv run
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "playwright",
# ]
# ///
"""Refresh YouTube cookies using Playwright with dedicated automation profile."""

import argparse
import sys
import time
from pathlib import Path
from typing import Any

# Persistent profile for automation (separate from system Chrome)
DEFAULT_PROFILE = Path.home() / ".config" / "youtube" / "playwright-profile"
DEFAULT_OUTPUT = Path.home() / ".config" / "youtube" / "cookies.txt"


def cookies_to_netscape(cookies: list[dict[str, Any]]) -> str:
    """Convert Playwright cookies to Netscape cookies.txt format."""
    lines = [
        "# Netscape HTTP Cookie File",
        "# https://curl.haxx.se/docs/http-cookies.html",
        f"# Refreshed by refresh_cookies.py at {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]

    for c in cookies:
        domain = c.get("domain", "")
        if ".youtube.com" not in domain and ".google.com" not in domain:
            continue

        include_subdomains = "TRUE" if domain.startswith(".") else "FALSE"
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure", False) else "FALSE"
        expiry = int(c.get("expires", time.time() + 86400 * 365))
        name = c.get("name", "")
        value = c.get("value", "")

        lines.append(f"{domain}\t{include_subdomains}\t{path}\t{secure}\t{expiry}\t{name}\t{value}")

    return "\n".join(lines)


def setup_profile(profile_dir: Path) -> bool:
    """Interactive setup: launch browser for user to log in to YouTube.

    Args:
        profile_dir: Where to store the persistent profile

    Returns:
        True if setup completed successfully
    """
    from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

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

        def capture_cookies():
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
            except Exception:
                pass

        # Capture cookies periodically and on close
        context.on("close", lambda: None)  # Keep context alive

        try:
            while len(context.pages) > 0:
                capture_cookies()
                time.sleep(2)
        except Exception:
            pass

        # Final capture attempt
        capture_cookies()

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
    from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

    if not profile_dir.exists():
        print(f"Error: Profile not found at {profile_dir}", file=sys.stderr)
        print("Run with --setup first to create the profile.", file=sys.stderr)
        return False

    print(f"Using profile: {profile_dir}")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
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

        page = context.new_page()

        print("Navigating to youtube.com...")
        try:
            page.goto("https://www.youtube.com", timeout=timeout, wait_until="networkidle")
        except Exception as e:
            print(f"Navigation warning (may still work): {e}", file=sys.stderr)

        # Wait for cookie rotation
        page.wait_for_timeout(2000)

        # Extract cookies
        cookies = context.cookies(["https://www.youtube.com", "https://accounts.google.com"])
        print(f"Extracted {len(cookies)} cookies")

        context.close()

    # Filter to YouTube-relevant cookies
    yt_cookies = [c for c in cookies if ".youtube.com" in c.get("domain", "") or ".google.com" in c.get("domain", "")]
    print(f"Filtered to {len(yt_cookies)} YouTube/Google cookies")

    # Check for essential auth cookies
    cookie_names = {c["name"] for c in yt_cookies}
    essential = {"SID", "HSID", "SSID", "APISID", "SAPISID"}
    missing = essential - cookie_names

    if missing:
        print(f"Warning: Missing essential cookies: {missing}", file=sys.stderr)
        print("Session may have expired. Run --setup again to re-login.", file=sys.stderr)
        return False

    # Save
    netscape = cookies_to_netscape(yt_cookies)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(netscape, encoding="utf-8")
    print(f"Saved {len(yt_cookies)} cookies to {output_path}")

    return True


def main():
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
    main()
