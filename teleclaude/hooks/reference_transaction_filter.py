"""Standalone git ``reference-transaction`` filter: report an ``origin/main`` advance, ignore everything else.

Git runs this hook about three times per ref transaction, so the no-match path imports nothing from
TeleClaude and starts no ``telec``. It runs under whatever ``python3`` the hook finds, which may be an
older interpreter than the platform's, so it uses only the standard library and no newer syntax.
It always exits 0 and never aborts a transaction.
"""

from __future__ import annotations

import re
import subprocess
import sys

COMMITTED_STATE = "committed"
ORIGIN_MAIN_REFERENCE = "refs/remotes/origin/main"
ENTRY_COMMAND = ("telec", "repo", "remote-main")
OBJECT_ID_PATTERN = re.compile(r"[0-9a-f]{40,64}")
NULL_OBJECT_ID_PATTERN = re.compile(r"0{40,64}")
UPDATE_FIELD_COUNT = 3


def advanced_origin_main(line: str) -> tuple[str, str] | None:
    """The previous and new object ids of an ``origin/main`` update line, or ``None`` when the line is another ref, a deletion, or malformed."""
    fields = line.split()
    if len(fields) != UPDATE_FIELD_COUNT or fields[2] != ORIGIN_MAIN_REFERENCE:
        return None
    previous, new, _reference = fields
    if not OBJECT_ID_PATTERN.fullmatch(previous) or not OBJECT_ID_PATTERN.fullmatch(new):
        return None
    if NULL_OBJECT_ID_PATTERN.fullmatch(new):
        return None
    return previous, new


def main(argv: list[str]) -> int:
    """Read the transaction on stdin once it is committed and hand an ``origin/main`` advance to the platform."""
    if len(argv) < 2 or argv[1] != COMMITTED_STATE:
        return 0
    for line in sys.stdin:
        advance = advanced_origin_main(line)
        if advance is None:
            continue
        try:
            # The platform entry is the only owner of recording; no native alternative exists in a standalone hook.
            subprocess.run([*ENTRY_COMMAND, *advance], check=False)
        except OSError:
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
