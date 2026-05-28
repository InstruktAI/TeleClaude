"""Regression coverage for REDIS_URL locality classification in install.sh.

Exercises bin/init/redis_locality.sh directly: the host parse and the
loopback-vs-remote decision that gates the local Redis install prompt.
One test per distinct parse/decision path.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_HELPER = Path(__file__).resolve().parents[3] / "bin" / "init" / "redis_locality.sh"


def _classify(url: str) -> tuple[str, bool]:
    host = subprocess.run(
        ["bash", "-c", f'source "{_HELPER}"; redis_url_host "$1"', "_", url],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    is_local = (
        subprocess.run(
            ["bash", "-c", f'source "{_HELPER}"; redis_url_is_local "$1"', "_", url],
            check=False,
        ).returncode
        == 0
    )
    return host, is_local


def test_localhost_is_local_case_insensitively() -> None:
    # Non-bracketed host path: surrounding quotes stripped, host lowercased.
    expected_host = "localhost"
    host, is_local = _classify('"redis://LOCALHOST:6379"')
    assert host == expected_host
    assert is_local is True


def test_loopback_range_beyond_dot_one_is_local() -> None:
    # 127.0.0.0/8 is loopback, not just 127.0.0.1.
    expected_host = "127.0.0.5"
    host, is_local = _classify("redis://127.0.0.5:6379")
    assert host == expected_host
    assert is_local is True


def test_bracketed_ipv6_loopback_is_local() -> None:
    # Bracketed IPv6 parse path: brackets stripped before the ::1 match.
    expected_host = "::1"
    host, is_local = _classify("redis://[::1]:6379")
    assert host == expected_host
    assert is_local is True


def test_remote_host_with_credentials_is_remote() -> None:
    # Credentials stripped; a remote host that merely contains "localhost" stays remote.
    expected_host = "cache.localhost.example"
    host, is_local = _classify("rediss://user:pass@cache.localhost.example:6478")
    assert host == expected_host
    assert is_local is False


def test_empty_url_is_not_local() -> None:
    # No URL configured -> no host -> not classified local (install falls to the prompt).
    host, is_local = _classify("")
    assert not host
    assert is_local is False
