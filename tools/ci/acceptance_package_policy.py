#!/usr/bin/python3.12
"""Guest package-service policy installed only during enclosed OS configuration."""

from __future__ import annotations

SERVICE_ACTION_DENIED = 101


def main() -> int:
    """Decline every maintainer-script service action while the guest is configured."""
    return SERVICE_ACTION_DENIED


if __name__ == "__main__":
    raise SystemExit(main())
