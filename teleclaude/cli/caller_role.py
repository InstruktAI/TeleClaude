"""Print the resolved caller roles for shell entrypoints that need them."""

from __future__ import annotations

import sys

from teleclaude.caller_identity import PersonCliCaller, ProjectPath, RoleResolver
from teleclaude.cli.session_auth import resolve_cli_identity
from teleclaude.paths import invocation_cwd


def main() -> None:
    """Write the caller's system and person roles as two shell-readable lines."""
    try:
        identity = resolve_cli_identity()
    except Exception as exc:
        print("system_role=")
        print("person_role=")
        print(f"caller identity resolution failed: {exc}", file=sys.stderr)
        return
    print(f"system_role={identity.system_role or ''}")
    person_role = (
        RoleResolver().role_for(identity.caller, ProjectPath(invocation_cwd()))
        if isinstance(identity.caller, PersonCliCaller)
        else None
    )
    print(f"person_role={person_role or ''}")


if __name__ == "__main__":
    main()
