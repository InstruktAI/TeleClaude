"""Shared deployment helpers."""

from __future__ import annotations


def parse_version(ver: str) -> tuple[int, int, int]:
    """Parse a semantic version string into integer parts.

    Accepts either ``1.2.3`` or ``v1.2.3``.
    """
    normalized = ver.strip()
    if normalized.startswith("v"):
        normalized = normalized[1:]

    parts = normalized.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        raise ValueError(f"Invalid semantic version: {ver!r}")

    major, minor, patch = parts
    return (int(major), int(minor), int(patch))


def version_cmp(a: str, b: str) -> int:
    """Compare two semantic versions."""
    a_parts = parse_version(a)
    b_parts = parse_version(b)
    if a_parts < b_parts:
        return -1
    if a_parts > b_parts:
        return 1
    return 0


def version_in_range(ver: str, from_ver: str, to_ver: str) -> bool:
    """Return ``True`` when ``from_ver < ver <= to_ver``."""
    if version_cmp(from_ver, to_ver) > 0:
        raise ValueError(f"Invalid version range: {from_ver!r} > {to_ver!r}")
    return version_cmp(from_ver, ver) < 0 and version_cmp(ver, to_ver) <= 0


__all__ = ["parse_version", "version_cmp", "version_in_range"]
