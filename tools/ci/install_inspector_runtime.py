"""Install pinned release inspectors into one verified provider-visible bootstrap."""

from __future__ import annotations

import argparse
from pathlib import Path

from tools.ci.gha import required_env
from tools.release.inspector_bootstrap import BOOTSTRAP_RECEIPT_FILENAME, create_bootstrap
from tools.release.isolated_inspection import InspectorRole

_DESCRIPTION = "Prepare the owned release inspector bootstrap."
_EVIDENCE_OPTION = "--evidence"
_PROVIDER_OPTION = "--provider"
_RUNNER_TEMP = "RUNNER_TEMP"
_NODE_VERSION = "NODE_VERSION"
_CODEX_VERSION = "CODEX_CLI_VERSION"
_CLAUDE_VERSION = "CLAUDE_CODE_VERSION"


def main(argv: list[str] | None = None) -> int:
    """Persist only a secret-free locator inside private job temporary storage."""
    parser = argparse.ArgumentParser(description=_DESCRIPTION)
    parser.add_argument(_EVIDENCE_OPTION, type=Path, required=True)
    parser.add_argument(_PROVIDER_OPTION, choices=[role.value for role in InspectorRole], required=True)
    args = parser.parse_args(argv)
    role = InspectorRole(args.provider)
    receipt = Path(required_env(_RUNNER_TEMP)).resolve() / BOOTSTRAP_RECEIPT_FILENAME
    create_bootstrap(
        args.evidence,
        receipt,
        {role: required_env(_CODEX_VERSION if role is InspectorRole.CODEX else _CLAUDE_VERSION)},
        int(required_env(_NODE_VERSION)),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
