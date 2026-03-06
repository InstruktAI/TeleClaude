"""CLI surface for cartridge lifecycle management.

Handles:
  telec config cartridges install --path <src> --scope <scope> --target <name>
  telec config cartridges remove --id <id> --scope <scope> --target <name>
  telec config cartridges promote --id <id> --from <scope> --to <scope> --domain <name>
  telec config cartridges list [--domain <name>] [--member <id>]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teleclaude_events.lifecycle import LifecycleManager


def _get_lifecycle_manager() -> "LifecycleManager":
    """Build a LifecycleManager from global config."""
    from teleclaude.config.loader import load_global_config
    from teleclaude_events.lifecycle import LifecycleManager

    config = load_global_config()
    event_domains = getattr(config, "event_domains", None)

    if event_domains is not None:
        base_path = Path(event_domains.base_path).expanduser()
        personal_base = Path(event_domains.personal_base_path).expanduser()
    else:
        base_path = Path("~/.teleclaude/company").expanduser()
        personal_base = Path("~/.teleclaude/personal").expanduser()

    return LifecycleManager(
        personal_base_path=personal_base,
        domain_base_path=base_path,
    )


def _caller_is_admin() -> bool:
    """Determine if the current session caller has admin role.

    Reads the session ID from $TMPDIR/teleclaude_session_id and looks up
    human_role via sync DB query, matching the pattern in config_cli.py.
    Returns False when not in a session context or on any error (fail closed).
    """
    tmpdir = os.environ.get("TMPDIR", "")
    if not tmpdir:
        return False
    session_file = Path(tmpdir) / "teleclaude_session_id"
    if not session_file.exists():
        return False
    try:
        session_id = session_file.read_text(encoding="utf-8").strip()
    except Exception:
        return False
    if not session_id:
        return False
    try:
        from teleclaude.config import config
        from teleclaude.core.db import get_session_field_sync

        role = get_session_field_sync(config.database.path, session_id, "human_role")
        return role == "admin"
    except Exception:
        return False


def handle_cartridge_cli(args: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="telec config cartridges", add_help=True)
    subparsers = parser.add_subparsers(dest="action")

    # install
    p_install = subparsers.add_parser("install", help="Install a cartridge")
    p_install.add_argument("--path", required=True, help="Source cartridge directory path")
    p_install.add_argument("--scope", required=True, choices=["personal", "domain", "platform"])
    p_install.add_argument("--target", required=True, help="Target name (member id or domain name)")
    p_install.add_argument("--json", action="store_true", help="Output JSON")

    # remove
    p_remove = subparsers.add_parser("remove", help="Remove a cartridge")
    p_remove.add_argument("--id", required=True, dest="cartridge_id", help="Cartridge ID")
    p_remove.add_argument("--scope", required=True, choices=["personal", "domain", "platform"])
    p_remove.add_argument("--target", required=True, help="Target name")
    p_remove.add_argument("--json", action="store_true", help="Output JSON")

    # promote
    p_promote = subparsers.add_parser("promote", help="Promote a cartridge to a higher scope")
    p_promote.add_argument("--id", required=True, dest="cartridge_id", help="Cartridge ID")
    p_promote.add_argument("--from", required=True, dest="from_scope", choices=["personal", "domain", "platform"])
    p_promote.add_argument("--to", required=True, dest="to_scope", choices=["personal", "domain", "platform"])
    p_promote.add_argument("--domain", required=True, dest="target_domain", help="Target domain name")
    p_promote.add_argument(
        "--member", default=None, dest="source_member_id", help="Source member id (required when --from=personal)"
    )
    p_promote.add_argument("--json", action="store_true", help="Output JSON")

    # list
    p_list = subparsers.add_parser("list", help="List installed cartridges")
    p_list.add_argument("--domain", default=None, help="Filter by domain name")
    p_list.add_argument("--member", default=None, help="Filter by member id")
    p_list.add_argument("--json", action="store_true", help="Output JSON")

    parsed = parser.parse_args(args)

    if parsed.action is None:
        parser.print_help()
        sys.exit(1)

    from teleclaude_events.lifecycle import CartridgeScope

    try:
        manager = _get_lifecycle_manager()
        is_admin = _caller_is_admin()
        use_json = getattr(parsed, "json", False)

        if parsed.action == "install":
            manager.install(
                source_path=Path(parsed.path).expanduser(),
                scope=CartridgeScope(parsed.scope),
                target=parsed.target,
                caller_is_admin=is_admin,
            )
            result = {"ok": True, "action": "install", "scope": parsed.scope, "target": parsed.target}
            if use_json:
                print(json.dumps(result))
            else:
                print(f"Installed cartridge from {parsed.path} to {parsed.scope}/{parsed.target}")

        elif parsed.action == "remove":
            manager.remove(
                cartridge_id=parsed.cartridge_id,
                scope=CartridgeScope(parsed.scope),
                target=parsed.target,
                caller_is_admin=is_admin,
            )
            result = {"ok": True, "action": "remove", "id": parsed.cartridge_id}
            if use_json:
                print(json.dumps(result))
            else:
                print(f"Removed cartridge '{parsed.cartridge_id}' from {parsed.scope}/{parsed.target}")

        elif parsed.action == "promote":
            manager.promote(
                cartridge_id=parsed.cartridge_id,
                from_scope=CartridgeScope(parsed.from_scope),
                to_scope=CartridgeScope(parsed.to_scope),
                target_domain=parsed.target_domain,
                caller_is_admin=is_admin,
                source_member_id=getattr(parsed, "source_member_id", None),
            )
            result = {
                "ok": True,
                "action": "promote",
                "id": parsed.cartridge_id,
                "from": parsed.from_scope,
                "to": parsed.to_scope,
            }
            if use_json:
                print(json.dumps(result))
            else:
                print(f"Promoted cartridge '{parsed.cartridge_id}' from {parsed.from_scope} to {parsed.to_scope}")

        elif parsed.action == "list":
            rows: list[dict[str, str]] = []
            if parsed.domain:
                rows.extend(manager.list_cartridges(CartridgeScope.domain, parsed.domain))
            elif parsed.member:
                rows.extend(manager.list_cartridges(CartridgeScope.personal, parsed.member))
            else:
                # List all domains from config
                from teleclaude.config.loader import load_global_config

                config = load_global_config()
                event_domains = getattr(config, "event_domains", None)
                if event_domains:
                    for domain_name in event_domains.domains:
                        rows.extend(manager.list_cartridges(CartridgeScope.domain, domain_name))
            if use_json:
                print(json.dumps(rows))
            else:
                if not rows:
                    print("No cartridges found.")
                else:
                    print(f"{'ID':<30} {'VERSION':<10} {'SCOPE':<10} {'TARGET':<20} DESCRIPTION")
                    print("-" * 90)
                    for row in rows:
                        print(
                            f"{row['id']:<30} {row['version']:<10} {row['scope']:<10} "
                            f"{row['target']:<20} {row['description']}"
                        )

    except PermissionError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
