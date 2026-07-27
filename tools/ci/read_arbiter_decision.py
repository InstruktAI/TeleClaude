"""Replace the Extract Decision step in release.yaml."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.ci.gha import append_output

ARBITER_FILE = "arbiter-decision.json"
DESCRIPTION = "Export arbiter decision outputs."
FALSE = "false"
NULL = "null"
RELEASE_AUTHORIZED = "release_authorized"
TARGET_VERSION = "target_version"
TRUE = "true"


def jq_raw(value: object) -> str:
    """Render a JSON value as jq -r renders this workflow's scalar values."""
    if value is None:
        return NULL
    if value is True:
        return TRUE
    if value is False:
        return FALSE
    if isinstance(value, str | int | float):
        return str(value)
    return json.dumps(value, separators=(",", ":"))


def main(argv: list[str] | None = None) -> int:
    """Print and export the two arbiter decision fields."""
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--file", default=ARBITER_FILE)
    args = parser.parse_args(argv)
    source = Path(args.file)
    content = source.read_text(encoding="utf-8")
    print(content, end="")
    payload = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError("arbiter decision must be a JSON object")
    append_output(RELEASE_AUTHORIZED, jq_raw(payload.get(RELEASE_AUTHORIZED)))
    append_output(TARGET_VERSION, jq_raw(payload.get(TARGET_VERSION)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
