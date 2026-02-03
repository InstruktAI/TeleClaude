# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "playwright",
# ]
# ///
"""Refresh YouTube cookies using Playwright with existing Chrome profile.

Visits youtube.com to trigger server-side token rotation, extracts
fresh cookies, and saves them in Netscape format.

Usage:
    uv run scripts/refresh_cookies.py
    uv run scripts/refresh_cookies.py --profile ~/.config/google-chrome
    uv run scripts/refresh_cookies.py --output ~/cookies.txt
"""

import argparse
import sys
import time
from pathlib import Path

# Default paths
DEFAULT_CHROME_PROFILE = Path.home() / "Library" / "Application Support" / "Google" / "Chrome"
DEFAULT_OUTPUT = Path.home() / ".config" / "youtube" / "cookies.txt"


def cookies_to_netscape(cookies: list[dict]) -> str:
    """Convert Playwright cookies to Netscape cookies.txt format."""
    lines = [
        "# Netscape HTTP Cookie File",
        "# https://curl.haxx.se/docs/http-cookies.html",
        "# Refreshed by refresh_cookies.py",
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


def refresh_cookies(
    chrome_profile: Path,
    output_path: Path,
    headless: bool = False,
    timeout: int = 30000,
) -> bool:
    """Refresh YouTube cookies by visiting the site with existing Chrome session.

    Args:
        chrome_profile: Path to Chrome user data directory (or dedicated automation profile)
        output_path: Where to save cookies.txt
        headless: Run headless (not recommended, may trigger detection)
        timeout: Page load timeout in ms

    Returns:
        True if successful
    """
    import shutil
    import tempfile

    from playwright.sync_api import sync_playwright

    print(f"Using Chrome profile: {chrome_profile}")

    if not chrome_profile.exists():
        print(f"Error: Chrome profile not found at {chrome_profile}", file=sys.stderr)
        return False

    # Check if this is the main Chrome profile (likely in use)
    # SingletonLock is a symlink on POSIX, use is_symlink() not exists()
    singleton_lock = chrome_profile / "SingletonLock"
    if singleton_lock.is_symlink() or singleton_lock.exists():
        print("Chrome is running with this profile. Using temporary copy...")
        # Copy essential cookie files to temp dir
        temp_dir = Path(tempfile.mkdtemp(prefix="chrome_cookies_"))
        default_profile = chrome_profile / "Default"
        temp_default = temp_dir / "Default"
        temp_default.mkdir(parents=True)

        # Copy only what we need for cookies
        for f in ["Cookies", "Cookies-journal", "Preferences", "Secure Preferences"]:
            src = default_profile / f
            if src.exists():
                shutil.copy2(src, temp_default / f)

        # Also copy Local State for encryption keys
        local_state = chrome_profile / "Local State"
        if local_state.exists():
            shutil.copy2(local_state, temp_dir / "Local State")

        use_profile = temp_dir
        cleanup_temp = True
        print(f"Copied profile to {temp_dir}")
    else:
        use_profile = chrome_profile
        cleanup_temp = False

    try:
        with sync_playwright() as p:
            # Launch Chrome with profile
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(use_profile),
                headless=headless,
                channel="chrome",
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
            )

            page = context.new_page()

            print("Navigating to youtube.com...")
            try:
                page.goto("https://www.youtube.com", timeout=timeout, wait_until="networkidle")
            except Exception as e:
                print(f"Navigation error (may still work): {e}", file=sys.stderr)

            # Brief wait for any final cookie rotation
            page.wait_for_timeout(2000)

            # Extract cookies
            cookies = context.cookies(["https://www.youtube.com", "https://accounts.google.com"])
            print(f"Extracted {len(cookies)} cookies")

            context.close()

        # Filter to YouTube-relevant cookies
        yt_cookies = [
            c for c in cookies if ".youtube.com" in c.get("domain", "") or ".google.com" in c.get("domain", "")
        ]
        print(f"Filtered to {len(yt_cookies)} YouTube/Google cookies")

        # Check for essential auth cookies
        cookie_names = {c["name"] for c in yt_cookies}
        essential = {"SID", "HSID", "SSID", "APISID", "SAPISID"}
        missing = essential - cookie_names
        if missing:
            print(f"Warning: Missing essential cookies: {missing}", file=sys.stderr)
            print("You may need to log in to YouTube in Chrome first.", file=sys.stderr)
            return False

        # Save
        netscape = cookies_to_netscape(yt_cookies)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(netscape, encoding="utf-8")
        print(f"Saved {len(yt_cookies)} cookies to {output_path}")

        return True

    except Exception as e:
        print(f"Error during cookie refresh: {e}", file=sys.stderr)
        return False

    finally:
        # Cleanup temp profile if we created one
        if cleanup_temp and use_profile.exists():
            shutil.rmtree(use_profile, ignore_errors=True)
            print("Cleaned up temporary profile")


def main():
    parser = argparse.ArgumentParser(description="Refresh YouTube cookies via Playwright")
    parser.add_argument(
        "--profile",
        type=Path,
        default=DEFAULT_CHROME_PROFILE,
        help=f"Chrome user data directory (default: {DEFAULT_CHROME_PROFILE})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output cookies.txt path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run headless (not recommended)",
    )
    args = parser.parse_args()

    success = refresh_cookies(
        chrome_profile=args.profile,
        output_path=args.output,
        headless=args.headless,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
