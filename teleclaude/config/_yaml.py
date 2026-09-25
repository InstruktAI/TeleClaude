"""The round-trip YAML parser configuration files are read and rewritten with."""

from __future__ import annotations

from ruamel.yaml import YAML


def round_trip_yaml() -> YAML:
    """Return a fresh quote-preserving round-trip parser for one load or dump.

    A ruamel parser holds per-document scanner state, so one instance shared by
    concurrent config loads corrupts each other's parse.
    """
    parser = YAML()
    parser.preserve_quotes = True
    return parser
