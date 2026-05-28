"""Regression coverage for REDIS_URL locality classification in install.sh.

Exercises the skip-local-Redis decision (`redis_url_skips_local_install` in
bin/init/redis_locality.sh) that install.sh calls verbatim. The contract:
skip only for a non-empty, non-loopback host. One test per parse/decision branch.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_HELPER = Path(__file__).resolve().parents[3] / "bin" / "init" / "redis_locality.sh"


def _skips_local_install(redis_url: str) -> bool:
    return (
        subprocess.run(
            ["bash", "-c", f'source "{_HELPER}"; redis_url_skips_local_install "$1"', "_", redis_url],
            check=False,
        ).returncode
        == 0
    )


def test_localhost_does_not_skip_case_insensitively() -> None:
    # Non-bracketed parse: quotes stripped, host lowercased, localhost is loopback.
    assert _skips_local_install('"redis://LOCALHOST:6379"') is False


def test_numeric_loopback_range_does_not_skip() -> None:
    # The whole 127.0.0.0/8 is loopback, not just 127.0.0.1.
    assert _skips_local_install("redis://127.0.0.5:6379") is False


def test_invalid_127_octets_are_not_loopback() -> None:
    # 127.x.x.x with an out-of-range octet is not valid loopback -> remote.
    assert _skips_local_install("redis://127.999.999.999:6379") is True


def test_bracketed_ipv6_loopback_does_not_skip() -> None:
    # Bracketed IPv6 parse path: brackets stripped before the ::1 match.
    assert _skips_local_install("redis://[::1]:6379") is False


def test_remote_host_with_credentials_skips() -> None:
    # Credentials stripped; a remote host that merely contains "localhost" still skips.
    assert _skips_local_install("rediss://user:pass@cache.localhost.example:6478") is True


def test_hostless_url_does_not_skip() -> None:
    # "redis://" has no host: not a remote endpoint, so install must still prompt.
    assert _skips_local_install("redis://") is False
