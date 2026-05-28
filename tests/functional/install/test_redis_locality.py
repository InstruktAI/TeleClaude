"""Regression coverage for REDIS_URL locality classification in install.sh.

Exercises bin/init/redis_locality.sh directly. The contract is the
skip-local-Redis decision: skip only for a non-empty, non-loopback host.
One test per distinct parse/decision path; assertions are boolean.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_HELPER = Path(__file__).resolve().parents[3] / "bin" / "init" / "redis_locality.sh"


def _host(url: str) -> str:
    return subprocess.run(
        ["bash", "-c", f'source "{_HELPER}"; redis_url_host "$1"', "_", url],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _is_loopback(host: str) -> bool:
    return (
        subprocess.run(
            ["bash", "-c", f'source "{_HELPER}"; redis_host_is_loopback "$1"', "_", host],
            check=False,
        ).returncode
        == 0
    )


def test_localhost_is_loopback_case_insensitively() -> None:
    # Non-bracketed parse path: quotes stripped, host lowercased, localhost matched.
    assert _is_loopback(_host('"redis://LOCALHOST:6379"')) is True


def test_numeric_loopback_range_is_loopback() -> None:
    # The whole 127.0.0.0/8 is loopback, not just 127.0.0.1.
    assert _is_loopback(_host("redis://127.0.0.5:6379")) is True


def test_non_numeric_127_hostname_is_not_loopback() -> None:
    # A hostname that merely starts with "127." is remote, not loopback.
    host = _host("redis://127.example.com:6379")
    assert host
    assert _is_loopback(host) is False


def test_bracketed_ipv6_loopback_is_loopback() -> None:
    # Bracketed IPv6 parse path: brackets stripped before the ::1 match.
    assert _is_loopback(_host("redis://[::1]:6379")) is True


def test_remote_host_with_credentials_is_not_loopback() -> None:
    # Credentials stripped; a remote host containing "localhost" stays remote (skips).
    host = _host("rediss://user:pass@cache.localhost.example:6478")
    assert host
    assert _is_loopback(host) is False


def test_hostless_url_yields_no_host() -> None:
    # "redis://" has no host: neither remote nor loopback, so install must prompt.
    assert not _host("redis://")
