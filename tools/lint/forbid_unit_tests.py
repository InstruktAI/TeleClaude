"""Forbid unit tests.

Behavior is verified by human-owned functional and integration tests bound to
the feature specs — not by agent-authored unit tests, which grade the author's
own code and tend toward green-theater. This check fails if any unit-tier test
is tracked, enforcing the no-unit-test policy structurally instead of relying on
review to catch it.

It inspects the git index (the staged tree that is being committed), not the
working filesystem — so it reports exactly what a commit introduces and is not
fooled by the pre-commit framework's transient working-tree stash.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main(repo_root: Path | None = None) -> None:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[2]

    result = subprocess.run(
        ["git", "ls-files", "--", "tests/unit"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    offenders = sorted(
        line for line in result.stdout.splitlines() if line.endswith(".py") and Path(line).name.startswith("test_")
    )

    if offenders:
        print("FORBIDDEN UNIT TESTS:")
        for path in offenders:
            print(f"  {path}")
        print()
        print(f"Total: {len(offenders)} unit test file(s).")
        print("Unit tests are not permitted. Behavior is verified by functional/integration")
        print("tests bound to the feature specs — move coverage there or delete the test.")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
